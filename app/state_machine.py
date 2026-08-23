"""状态机：待机(听唤醒) → 指令识别 → 执行。支持无硬件文本注入模式。"""
from __future__ import annotations

import logging
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
        from .audio.mic import BufferedMic

        # 采集/处理线程解耦：采集线程始终实时读走麦克风，避免处理慢导致 ALSA
        # 缓冲溢出 overrun；处理慢时只是队列积压（丢旧块），不再整段丢音频。
        mic = BufferedMic(self.mic)
        self.running = True
        mic.open()
        try:
            while self.running:
                chunk = mic.read_chunk(self.chunk_bytes)
                self._process_chunk(chunk)
        finally:
            mic.close()

    def _process_chunk(self, chunk: bytes) -> None:
        if self.state == STATE_IDLE:
            evt = self.vad.feed(chunk)
            if evt in ("speech_start", "speech_continue"):
                if self.wake is not None and self.wake.accept_waveform(
                    self._samples(chunk)
                ):
                    self._on_wake()
            return

        if self.state == STATE_LISTENING:
            now = time.monotonic()
            if now > self._wake_at + self.wake_timeout_ms / 1000.0:
                self._phase("等待指令超时，回到待机")
                self._go_idle()
                return
            if now < self._listen_from:
                # 唤醒提示音（"你好"）播放期间：丢弃麦克风音频，避免被识别进指令
                return
            # 进入指令录音（从提示音结束后第一次喂 ASR 起算）
            if not getattr(self, "_recording", False):
                self._recording = True
                self._phase("录音开始（提示音结束，可开始说指令）")
            self.asr.accept_waveform(self._samples(chunk))
            if self.asr.is_endpoint():
                self._on_utterance_done()

    def _on_wake(self) -> None:
        self._phase("唤醒成功")
        self._phase_t0 = time.monotonic()  # 重置阶段计时
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
        self._wake_at = time.monotonic()
        # 提示音 + 余量 播放期间丢弃麦克风音频，确保"你好"不被录进指令。
        # 按实际提示音时长计算静默期，避免固定 700ms 造成的多余等待。
        fb_dur = self.speaker.say_duration("你好") if self.speaker else 0.0
        grace = self.post_wake_grace_ms / 1000.0
        self._listen_from = self._wake_at + fb_dur + grace
        self._phase(f"静默期 {fb_dur:.2f}s+{grace:.2f}s，之后可开始说指令")
        if self.asr:
            self.asr.reset()
        self._recording = False

    def _on_utterance_done(self) -> None:
        self._phase("录音结束（指令说完）")
        text = self.asr.get_text() if self.asr else ""
        if self.asr:
            self.asr.reset()
        if not text:
            if self.speaker:
                self.speaker.say("听不懂")  # 空识别/没听清
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

    @staticmethod
    def _samples(chunk: bytes):
        """PCM 字节 → float32 numpy（sherpa-onnx 新版 API 需要）。"""
        return pcm_bytes_to_float32(chunk)
