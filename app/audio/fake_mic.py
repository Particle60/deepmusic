"""假麦克风：从 WAV 文件回放 PCM，接口与真麦一致（开发期替代麦克风）。"""
from __future__ import annotations

import wave
from typing import Optional

from .mic import MicReader


class FakeMicReader(MicReader):
    """从 16kHz/16bit/mono WAV 文件逐块回放；播完补静音，可循环。"""

    def __init__(
        self,
        wav_path: str,
        chunk_bytes: int = 3200,
        loop: bool = False,
    ):
        self.wav_path = wav_path
        self.chunk_bytes = chunk_bytes
        self.loop = loop
        self.eof = False  # 是否已读到文件末尾（仅非 loop 模式）
        self._wf: Optional[wave.Wave_read] = None

    def open(self) -> None:
        self._wf = wave.open(self.wav_path, "rb")
        self.eof = False

    def read_chunk(self, size: Optional[int] = None) -> bytes:
        size = size or self.chunk_bytes
        if self._wf is None:
            self.eof = True
            return b"\x00" * size
        # 假定 WAV 为 16bit（每帧 2 字节），上层统一按 16k/16bit 处理
        data = self._wf.readframes(size // 2)
        if self.loop:
            while len(data) < size:
                self._wf.rewind()
                data += self._wf.readframes((size - len(data)) // 2)
            return data[:size]
        if len(data) < size:
            self.eof = True
            return data + b"\x00" * (size - len(data))
        return data

    def close(self) -> None:
        if self._wf is not None:
            self._wf.close()
            self._wf = None
