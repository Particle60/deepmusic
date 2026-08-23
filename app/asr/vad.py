"""静音检测（VAD）。默认用能量门控，无需额外依赖，可被 Silero-VAD 替换。"""
from __future__ import annotations

import struct


def rms(pcm: bytes) -> float:
    """计算 16bit PCM 的 RMS（近似音量）。"""
    if not pcm:
        return 0.0
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    s = sum(v * v for v in samples)
    return (s / n) ** 0.5


class EnergyVad:
    """基于能量 + 静音时长的 VAD：判定"是否在说话"与"一句话结束"。"""

    def __init__(
        self,
        threshold: float = 120.0,
        min_speech_ms: int = 100,
        silence_timeout_ms: int = 800,
        sample_rate: int = 16000,
        chunk_bytes: int = 3200,
    ):
        self.threshold = threshold
        # 每块采样数 = chunk_bytes / 2（16bit）
        samples_per_chunk = max(1, chunk_bytes // 2)
        self.min_speech_chunks = max(
            1, round(min_speech_ms / 1000.0 * sample_rate / samples_per_chunk)
        )
        self.silence_chunks = max(
            1, round(silence_timeout_ms / 1000.0 * sample_rate / samples_per_chunk)
        )
        self.speech_chunks = 0
        self.silence_count = 0
        self.speaking = False
        self.current_speech = False  # 当前块是否真正有声（供状态机判断是否喂 ASR）

    def feed(self, chunk: bytes) -> str:
        """返回事件：'speech_start' / 'speech_continue' / 'speech_end' / 'silence'。"""
        self.current_speech = rms(chunk) >= self.threshold
        if self.current_speech:
            self.silence_count = 0
            self.speech_chunks += 1
            if not self.speaking and self.speech_chunks >= self.min_speech_chunks:
                self.speaking = True
                return "speech_start"
            if self.speaking:
                return "speech_continue"
            return "silence"
        # 静音帧
        if self.speaking:
            self.silence_count += 1
            if self.silence_count >= self.silence_chunks:
                self.speaking = False
                self.speech_chunks = 0
                self.silence_count = 0
                return "speech_end"
            return "speech_continue"  # 短暂停顿仍视为语音中
        return "silence"

    def reset(self) -> None:
        """重置状态（唤醒/结束一轮交互时调用），避免把上一轮的语音状态带入。"""
        self.speaking = False
        self.speech_chunks = 0
        self.silence_count = 0
        self.current_speech = False
