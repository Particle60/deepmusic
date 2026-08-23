"""麦克风采集接口：ALSA（Linux 板）与 SoundDevice（跨平台/开发机）。"""
from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)


class MicReader:
    """麦克风采集接口：输出 16kHz/16bit/mono PCM 块。

    chunk_bytes 是实例属性（各实现自定），此处不定义 property，
    避免与子类 `self.chunk_bytes = ...` 赋值冲突。
    """

    def open(self) -> None:
        raise NotImplementedError

    def read_chunk(self, size: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def create_mic(mic: str = "", backend: str = "", sample_rate: int = 16000, chunk_bytes: int = 3200) -> MicReader:
    """按平台/配置创建麦克风。

    backend: "" 自动（linux→alsa，其他→sounddevice）/ "alsa" / "sounddevice"
    """
    b = (backend or "").lower()
    if not b:
        b = "alsa" if sys.platform.startswith("linux") else "sounddevice"
    if b == "alsa":
        return AlsaMicReader(device=mic, sample_rate=sample_rate, chunk_bytes=chunk_bytes)
    return SoundDeviceMicReader(device=mic, sample_rate=sample_rate, chunk_bytes=chunk_bytes)


class AlsaMicReader(MicReader):
    """用 arecord 从 ALSA 采集（Linux 开发板），输出原始 PCM（16k/16bit/mono）。"""

    def __init__(
        self,
        device: str = "",
        sample_rate: int = 16000,
        chunk_bytes: int = 3200,
        buffer_ms: int = 500,
    ):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_bytes = chunk_bytes  # 100ms @16k/16bit/mono
        self.buffer_us = buffer_ms * 1000  # ALSA 缓冲（微秒），默认 500ms
        self._proc: Optional[subprocess.Popen] = None

    def open(self) -> None:
        cmd = [
            "arecord",
            "-q",
            "-f", "S16_LE",
            "-r", str(self.sample_rate),
            "-c", "1",
            "-t", "raw",
            # 加大 ALSA 缓冲（微秒），吸收处理偶发卡顿，避免溢出 overrun
            "-B", str(self.buffer_us),
        ]
        if self.device:
            cmd += ["-D", self.device]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    def read_chunk(self, size: Optional[int] = None) -> bytes:
        size = size or self.chunk_bytes
        if self._proc is None or self._proc.stdout is None:
            return b"\x00" * size
        data = self._proc.stdout.read(size)
        if len(data) < size:
            data += b"\x00" * (size - len(data))
        return data

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None


class SoundDeviceMicReader(MicReader):
    """用 sounddevice（PortAudio）采集，跨平台，开发机/真机通用。"""

    def __init__(
        self,
        device: str = "",
        sample_rate: int = 16000,
        chunk_bytes: int = 3200,
        gain: float = 3.0,
    ):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_bytes = chunk_bytes
        self.gain = gain  # 增益，弥补小声说话
        self._stream = None

    def open(self) -> None:
        import sounddevice as sd  # type: ignore

        frames = self.chunk_bytes // 2  # 16bit
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=frames,
            device=self.device or None,
        )
        self._stream.start()

    def read_chunk(self, size: Optional[int] = None) -> bytes:
        import numpy as np  # type: ignore

        size = size or self.chunk_bytes
        frames = size // 2
        if self._stream is None:
            return b"\x00" * size
        data, _ = self._stream.read(frames)
        data = (data.reshape(-1) * self.gain).clip(-1, 1)
        return (data * 32767).astype(np.int16).tobytes()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class BufferedMic:
    """采集/处理线程解耦：采集放到独立线程，主线程从队列取块处理。

    背景：主循环若在每块上做慢处理（如 ASR 推理），read_chunk 就会长时间不读
    arecord 管道 → ALSA 缓冲溢出 → overrun（丢音频，指令听不清）。
    本类让采集线程始终实时排空管道；主线程处理慢时队列积压，最多丢队列里最旧的
    块（可控、可统计），而不是在 ALSA 层整段 overrun。

    用法：
        mic = BufferedMic(AlsaMicReader(...))
        mic.open()
        while running:
            chunk = mic.read_chunk()   # 从队列取，实时性好
        mic.close()
    """

    def __init__(self, mic: MicReader, maxsize: int = 20):
        self.mic = mic
        self.maxsize = maxsize  # 队列容量（块数），20 块 ≈ 2s
        self._q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=maxsize)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._dropped = 0
        self._last_drop_log = 0.0

    @property
    def chunk_bytes(self) -> int:
        return self.mic.chunk_bytes

    def open(self) -> None:
        self.mic.open()
        self._running = True
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._capture, daemon=True, name="mic-capture"
        )
        self._thread.start()

    def _capture(self) -> None:
        """独立线程：持续采集并放入队列，保证 arecord 管道被及时读走。"""
        try:
            while self._running:
                chunk = self.mic.read_chunk()
                if self._q.full():
                    # 处理跟不上：丢最旧一块，保持实时
                    self._dropped += 1
                    now = time.monotonic()
                    if now - self._last_drop_log >= 1.0:
                        log.warning(
                            "处理跟不上，已丢弃 %d 块音频（队列满，丢旧保新）", self._dropped
                        )
                        self._last_drop_log = now
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        pass
                self._q.put(chunk)
        finally:
            try:
                self._q.put_nowait(None)  # 通知消费端结束
            except queue.Full:
                pass

    def read_chunk(self, size: Optional[int] = None) -> bytes:
        size = size or self.mic.chunk_bytes
        try:
            item = self._q.get(timeout=0.5)
        except queue.Empty:
            return b"\x00" * size
        if item is None:
            return b"\x00" * size
        return item

    def close(self) -> None:
        self._running = False
        try:
            self._q.put_nowait(None)  # 唤醒可能阻塞在 get() 的主线程
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=1.0)
        self.mic.close()
