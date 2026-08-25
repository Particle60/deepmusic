"""麦克风采集接口：ALSA（Linux 板）与 SoundDevice（跨平台/开发机）。"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

class MicReader:
    """麦克风采集接口：输出 16kHz/16bit/mono PCM 块。"""

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
    ):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_bytes = chunk_bytes  # 100ms @16k/16bit/mono
        self._proc: Optional[subprocess.Popen] = None

    def open(self) -> None:
        cmd = [
            "arecord",
            "-q",
            "-f", "S16_LE",
            "-r", str(self.sample_rate),
            "-c", "1",
            "-t", "raw",
            # 加大 ALSA 缓冲（500ms），即使 CPU 偶发卡顿也能吸收不溢出，避免 overrun
            "-B", "500000",
            "--period-size", "3200",
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
