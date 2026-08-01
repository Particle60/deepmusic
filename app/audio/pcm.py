"""PCM 字节 ↔ numpy float32 转换（sherpa-onnx 新版 API 需要 float32）。"""
from __future__ import annotations

import numpy as np


def pcm_bytes_to_float32(data: bytes) -> np.ndarray:
    """把 16bit/16k/mono PCM 字节转为归一化 float32 数组（-1 ~ 1）。"""
    if not data:
        return np.zeros(0, dtype=np.float32)
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return a
