"""sherpa-onnx 流式中文识别封装（新版 API：OnlineRecognizer.from_paraformer）。

注意：sherpa-onnx >= 1.13 的 Python API 已简化，直接传文件路径的工厂方法
`OnlineRecognizer.from_paraformer(...)`；输入音频为 float32（-1~1）numpy 数组。
"""
from __future__ import annotations

import glob
import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


def _find_model_dir(model_dir: str) -> str:
    """若 model_dir 是版本号子目录的父目录，自动定位到含 .onnx 的子目录。"""
    if glob.glob(os.path.join(model_dir, "*.onnx")) or os.path.exists(
        os.path.join(model_dir, "tokens.txt")
    ):
        return model_dir
    for sub in sorted(glob.glob(os.path.join(model_dir, "*"))):
        if os.path.isdir(sub) and glob.glob(os.path.join(sub, "*.onnx")):
            return sub
    return model_dir


def _pick(model_dir: str, part: str, prefer_int8: bool = True) -> Optional[str]:
    """在模型目录中挑选 encoder/decoder 的 onnx 文件：优先 int8。"""
    cands = glob.glob(os.path.join(model_dir, f"{part}*.onnx"))
    if prefer_int8:
        int8s = [f for f in cands if "int8" in os.path.basename(f)]
        if int8s:
            cands = int8s
    if not cands:
        return None
    return sorted(cands)[0]


class AsrEngine:
    """封装 OnlineRecognizer：输入 16k float32 PCM，输出增量文本。"""

    def __init__(
        self,
        model_dir: str,
        sample_rate: int = 16000,
        feat_dim: int = 80,
        provider: str = "cpu",
        tokens: str = "tokens.txt",
    ):
        self.model_dir = model_dir
        self.sample_rate = sample_rate
        self.feat_dim = feat_dim
        self.provider = provider
        self.tokens = tokens
        self.recognizer = None
        self.stream = None

    def load(self) -> bool:
        """加载流式 paraformer 模型；失败返回 False。"""
        try:
            import sherpa_onnx  # type: ignore
        except ImportError:
            log.warning("sherpa-onnx 未安装，跳过 ASR 加载")
            return False

        md = _find_model_dir(self.model_dir)
        enc = _pick(md, "encoder")
        dec = _pick(md, "decoder")
        tok = os.path.join(md, self.tokens)
        if not enc or not dec or not os.path.exists(tok):
            log.error(
                "ASR 模型文件缺失于 %s（需要 encoder/decoder onnx + tokens.txt）",
                md,
            )
            return False

        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=tok,
            encoder=enc,
            decoder=dec,
            num_threads=1,  # 弱核单线程往往更快（无线程切换开销），板子实测为准
            sample_rate=self.sample_rate,
            feature_dim=self.feat_dim,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=300,
            provider=self.provider,
        )
        self.stream = self.recognizer.create_stream()
        return True

    def accept_waveform(self, samples_float32: np.ndarray) -> None:
        """喂入 float32 采样（16k），并解码可解码的帧。"""
        if self.recognizer is None or self.stream is None:
            return
        self.stream.accept_waveform(self.sample_rate, samples_float32)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)

    def finish(self) -> None:
        """标记输入结束，并解码剩余帧（整段回放时调用）。"""
        if self.recognizer is None or self.stream is None:
            return
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)

    def is_endpoint(self) -> bool:
        if self.recognizer is None or self.stream is None:
            return False
        return self.recognizer.is_endpoint(self.stream)

    def get_text(self) -> str:
        """取当前识别文本（新版返回 str）。"""
        if self.recognizer is None or self.stream is None:
            return ""
        res = self.recognizer.get_result(self.stream)
        return res.strip() if isinstance(res, str) else str(res).strip()

    def reset(self) -> None:
        if self.recognizer is not None:
            self.stream = self.recognizer.create_stream()
