"""状态机：待机(听唤醒) → 指令识别 → 执行。支持无硬件文本注入模式。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

from .asr.engine import AsrEngine
from .asr.vad import EnergyVad
from .asr.wake import WakeWordDetector
from .audio.mic import MicReader
from .audio.pcm import pcm_bytes_to_float32
from .audio.speaker import Speaker
from .commands.handler import CommandHandler
from .commands.parser import parse_command

log = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_LISTENING = "listening"  # 已唤醒，正在听指令

# 提示音（"你好"）异步播放的启动缓冲：speaker.say() 返回后 mpv 需要几百 ms
# 才真正发声。若静默期不算这段，提示音回声会被麦克风录进 ASR。
_SAY_STARTUP_MARGIN = 0.35  # 秒


class VoiceApp:
    """语音主循环：mic → VAD → KWS → ASR → 指令。

    - 无硬件/无模型：可用 `inject_text()` 文本注入直接驱动指令链路。
    - 有硬件/有模型：`run()` 进入语音循环。
    """

    def __init__(
        self,
        mic: Optional[MicReader],
        vad: Optional[EnergyVad],
        wake: Optional[WakeWordDetector],
        asr: Optional[AsrEngine],
        handler: CommandHandler,
        speaker: Optional[Speaker] = None,
        wake_timeout_ms: int = 3000,
        wake_feedback_ms: int = 700,
        post_wake_grace_ms: int = 300,
        chunk_bytes: int = 3200,
    ):
        self.mic = mic
        self.vad = vad
        self.wake = wake
        self.asr = asr
        self.handler = handler
        self.speaker = speaker
        self.wake_timeout_ms = wake_timeout_ms
        self.wake_feedback_ms = wake_feedback_ms
        self.post_wake_grace_ms = post_wake_grace_ms
        self.chunk_bytes = chunk_bytes
        self.state = STATE_IDLE
        self.running = False
        self._q: "queue.Queue[tuple]" = queue.Queue()  # 采集→处理 缓存队列（(采集时刻, chunk)）
        self._wake_at = 0.0
        self._listen_from = 0.0  # 唤醒提示音播完后的时间点，此前的音频丢弃
        self._resume_after_wake = False  # 唤醒时暂停了音乐，指令失败需恢复
        self._phase_t0 = 0.0  # 阶段计时起点（用于打印各节点相对时间）
        self._recording = False  # 是否正在录指令（提示音结束后置位）

    def _phase(self, label: str) -> None:
        """打印一个交互阶段节点（带相对时间），便于把握发指令时机。"""
        now = time.monotonic()
        if self._phase_t0:
            dt = now - self._phase_t0
            log.info("[阶段] %s  (+%.2fs)", label, dt)
        else:
            log.info("[阶段] %s", label)
        self._phase_t0 = now

    # ---- 文本注入（无硬件/无模型开发调试） ----
    def inject_text(self, text: str) -> None:
        """直接把文本当指令处理（跳过唤醒/ASR）。"""
        log.info("[text] %s", text)
        cmd = parse_command(text)
        log.info("[intent] %s %s", cmd.intent, cmd.args)
        self.handler.handle(cmd)

    # ---- 语音循环 ----
    def run(self) -> None:
        if self.mic is None or self.vad is None:
            log.error("语音模式需要麦克风与 VAD，请先接入硬件/使用 --voice")
            return
        self.running = True
        self.mic.open()
        threading.Thread(
            target=self._capture_loop, daemon=True, name="mic-capture"
        ).start()
        try:
            while self.running:
                try:
                    t, chunk = self._q.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._process_chunk(t, chunk)
        finally:
            self.mic.close()

    def _capture_loop(self) -> None:
        """采集线程：持续排空麦克风管道，把带时间戳的 chunk 放入缓存队列。

        关键：即使处理（ASR）很慢，采集也始终保持实时，从根上避免 ALSA overrun。
        """
        try:
            while self.running:
                chunk = self.mic.read_chunk(self.chunk_bytes)
                self._q.put((time.monotonic(), chunk))
        except Exception:  # noqa: BLE001
            if self.running:
                log.warning("采集线程异常退出", exc_info=True)

    def _clear_queue(self) -> None:
        """丢弃缓存队列里剩余的音频块（识别完成后已无用）。"""
        cleared = 0
        while True:
            try:
                self._q.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if cleared:
            log.info("丢弃 %d 块积压缓存", cleared)

    def _process_chunk(self, t: float, chunk: bytes) -> None:
        if self.state == STATE_IDLE:
            evt = self.vad.feed(chunk)
            if evt in ("speech_start", "speech_continue"):
                if self.wake is not None and self.wake.accept_waveform(
                    self._samples(chunk)
                ):
                    self._on_wake(t)  # 以采集时刻 t 作为唤醒起点
            return

        if self.state == STATE_LISTENING:
            # 超时/静默期一律按"采集时刻"t 判定，避免处理延迟导致误判
            if t > self._wake_at + self.wake_timeout_ms / 1000.0:
                self._phase("等待指令超时，回到待机")
                if self.speaker:
                    self.speaker.say_sync("指令超时")  # 同步播完再恢复音乐，避免重叠
                self._clear_queue()  # 丢弃剩余缓存
                self._resume_previous()  # 恢复唤醒前暂停的音乐
                self._go_idle()
                return
            if t < self._listen_from:
                # 唤醒提示音（"你好"）播放期间：丢弃麦克风音频，避免被识别进指令
                return
            # 进入指令录音（从提示音结束后第一次喂 ASR 起算）
            if not getattr(self, "_recording", False):
                self._recording = True
                self._phase("录音开始（提示音结束，可开始说指令）")
            self.asr.accept_waveform(self._samples(chunk))
            if self.asr.is_endpoint():
                self._on_utterance_done()

    def _on_wake(self, t: float) -> None:
        """唤醒。t 为命中唤醒词那一刻的采集时刻（用于对齐超时/静默期判定）。"""
        self._phase("唤醒成功")
        self._phase_t0 = time.monotonic()  # 重置阶段计时（仅用于日志）
        # 唤醒时暂停音乐，避免干扰听"你好"和指令
        if self.handler.pause_music():
            self._resume_after_wake = True
            self._phase("已暂停音乐")
        else:
            self._resume_after_wake = False
        if self.speaker:
            self._phase("回应开始（播放「你好」）")
            self.speaker.say("你好")  # 唤醒后反馈"你好"，提示已就绪
            self._phase("回应结束（「你好」播完）")
        self.state = STATE_LISTENING
        self._wake_at = t  # 以采集时刻为基准，避免处理延迟压缩超时窗口
        # 静默期基准 = 提示音 say() 调用后的处理时刻（与采集时间戳同为 monotonic，可比）。
        # 之所以不用 _wake_at：say() 是在 _wake_at 之后、由处理线程才调用的，
        # 中间隔了处理延迟；以 say() 时刻为基准才能确保提示音（含启动缓冲）的
        # 回声整体都被丢弃，否则会录进 ASR 变成指令开头的"你好"。
        t0 = time.monotonic()
        fb_dur = self.speaker.say_duration("你好") if self.speaker else 0.0
        grace = self.post_wake_grace_ms / 1000.0
        self._listen_from = t0 + fb_dur + _SAY_STARTUP_MARGIN + grace
        self._phase(f"静默期 {fb_dur:.2f}s+启动缓冲{_SAY_STARTUP_MARGIN:.2f}s+{grace:.2f}s，之后可开始说指令")
        if self.asr:
            self.asr.reset()
        self._recording = False

    def _on_utterance_done(self) -> None:
        self._phase("录音结束（指令说完）")
        self._clear_queue()  # 识别完成，剩余缓存已无用，直接丢弃
        # 关键：流式 ASR 的尾字需要"说完后的停顿静音"才能被解码。
        # 关键：流式 ASR 的尾字需要"说完后的停顿静音"才能被解码。
        # 实测：结尾补 ~0.5s 静音（8000 采样 @16k）再 finish，能把最后一个字解出来
        # （如"睡觉"→"睡觉"；0.25s 仍会丢尾字，故用 0.5s）。
        if self.asr:
            self.asr.accept_waveform(
                pcm_bytes_to_float32(b"\x00\x00" * 8000)  # 0.5s @16k 静音
            )
            self.asr.finish()
        text = self.asr.get_text() if self.asr else ""
        if self.asr:
            self.asr.reset()
        if not text:
            if self.speaker:
                self.speaker.say_sync("听不懂")  # 同步播完再恢复音乐，避免重叠
            self._resume_previous()
            self._go_idle()
            return
        self._phase(f"识别指令：{text}")
        cmd = parse_command(text)
        self.handler.handle(cmd)
        # 暂停/停止类指令保持状态，其余指令恢复唤醒前暂停的音乐
        if self.handler.should_resume_after():
            self._resume_previous()
        else:
            self._resume_after_wake = False  # 已由指令处理（暂停/停止），不再自动恢复
        self._go_idle()
        self._phase("回到待机（可再次唤醒）")

    def _resume_previous(self) -> None:
        """恢复唤醒前暂停的音乐（无论指令成功/失败都调用）。"""
        if self._resume_after_wake:
            log.info("恢复之前的音乐")
            self.handler.resume_previous()
            self._resume_after_wake = False

    def _go_idle(self) -> None:
        self.state = STATE_IDLE
        if self.wake:
            self.wake.reset()
        if self.vad:
            self.vad.speaking = False

    def stop(self) -> None:
        self.running = False
        if self.mic is not None:
            self.mic.close()  # 终止采集，让采集线程尽快退出

    @staticmethod
    def _samples(chunk: bytes):
        """PCM 字节 → float32 numpy（sherpa-onnx 新版 API 需要）。"""
        return pcm_bytes_to_float32(chunk)
