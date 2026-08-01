"""唤醒词检测（sherpa-onnx KWS 新版 API：直接传路径的 KeywordSpotter）。"""
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
    """挑选 encoder/decoder/joiner 的 onnx：优先 chunk-16，其次 int8。"""
    cands = [
        f
        for f in glob.glob(os.path.join(model_dir, f"{part}*.onnx"))
        if "chunk-16" in os.path.basename(f)
    ]
    if not cands:
        cands = glob.glob(os.path.join(model_dir, f"{part}*.onnx"))
    if prefer_int8:
        int8s = [f for f in cands if "int8" in os.path.basename(f)]
        if int8s:
            cands = int8s
    if not cands:
        return None
    # 同一 epoch 内 decoder 用 fp32（量化对 decoder 无益且官方默认 fp32）
    return sorted(cands)[0]


class WakeWordDetector:
    """封装 sherpa_onnx.KeywordSpotter：输入 16k float32 PCM，返回是否命中唤醒词。"""

    def __init__(
        self,
        model_dir: str,
        sample_rate: int = 16000,
        provider: str = "cpu",
        keywords_file: Optional[str] = None,
    ):
        self.model_dir = model_dir
        self.sample_rate = sample_rate
        self.provider = provider
        self.keywords_file = keywords_file
        self.spotter = None
        self.stream = None
        self._last_keyword = ""

    def load(self) -> bool:
        """加载 KWS 模型；sherpa-onnx 未安装或模型缺失时返回 False。"""
        try:
            import sherpa_onnx  # type: ignore
        except ImportError:
            log.warning("sherpa-onnx 未安装，跳过唤醒词加载")
            return False

        md = _find_model_dir(self.model_dir)
        enc = _pick(md, "encoder")
        dec = _pick(md, "decoder")
        joi = _pick(md, "joiner")
        tok = os.path.join(md, "tokens.txt")

        # 关键词文件：显式指定 > 模型根目录 keywords.txt > test_wavs/test_keywords.txt > test_wavs/keywords.txt
        kwf = self.keywords_file
        if not kwf or not os.path.exists(kwf):
            cands = [
                os.path.join(md, "keywords.txt"),
                os.path.join(md, "test_wavs", "test_keywords.txt"),
                os.path.join(md, "test_wavs", "keywords.txt"),
            ]
            kwf = next((c for c in cands if os.path.exists(c)), "")
        if not enc or not dec or not joi or not os.path.exists(tok) or not kwf:
            log.error(
                "KWS 模型/关键词文件缺失于 %s（需要 encoder/decoder/joiner onnx + tokens.txt + keywords 文件）",
                md,
            )
            return False

        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=tok,
            encoder=enc,
            decoder=dec,
            joiner=joi,
            keywords_file=kwf,
            num_threads=1,  # 与官方测试一致
            sample_rate=self.sample_rate,
            feature_dim=80,
            max_active_paths=4,
            # 实测：score=1.0/threshold=0.25（官方默认）在播放音乐时唤醒率太低，
            # 调高 score / 调低 threshold 更易命中（已用真人语音验证可唤醒）
            keywords_score=3.0,
            keywords_threshold=0.05,
            provider=self.provider,
        )
        # 注意：sherpa-onnx 1.13 的 decode_streams 在只有 1 个流时解码不充分，
        # 必须 ≥2 个流一起批量解码才能正确触发关键词。
        # 因此这里维护一个"主流 + 占位静音流"，全程用批量解码。
        self.stream = self.spotter.create_stream()
        self._dummy = self.spotter.create_stream()
        return True

    def _feed_dummy(self, n_samples: int) -> None:
        """给占位流喂与主流等量的静音，保证解码全程 ≥2 流。"""
        if self._dummy is None:
            return
        self._dummy.accept_waveform(
            self.sample_rate, np.zeros(n_samples, dtype=np.float32)
        )

    def accept_waveform(self, samples_float32: np.ndarray) -> bool:
        """喂入 float32 采样；返回本次是否命中唤醒词（命中后需 reset）。"""
        if self.spotter is None or self.stream is None:
            return False
        self.stream.accept_waveform(self.sample_rate, samples_float32)
        self._feed_dummy(len(samples_float32))
        streams = [self.stream, self._dummy]
        hit = False
        while True:
            ready = [ss for ss in streams if self.spotter.is_ready(ss)]
            for ss in streams:
                r = self.spotter.get_result(ss)
                if r:
                    if ss is self.stream:
                        self._last_keyword = r
                        hit = True
                    self.spotter.reset_stream(ss)
            if not ready:
                break
            self.spotter.decode_streams(ready)
        return hit

    def finalize(self) -> None:
        """喂入 0.66s 尾静音并标记输入结束，促使关键词解码完成（离线回放用）。"""
        if self.spotter is None or self.stream is None:
            return
        tail = np.zeros(int(0.66 * self.sample_rate), dtype=np.float32)
        self.stream.accept_waveform(self.sample_rate, tail)
        self._feed_dummy(len(tail))
        self.stream.input_finished()
        self._dummy.input_finished()
        streams = [self.stream, self._dummy]
        while True:
            ready = [ss for ss in streams if self.spotter.is_ready(ss)]
            for ss in streams:
                r = self.spotter.get_result(ss)
                if r:
                    if ss is self.stream:
                        self._last_keyword = r
                    self.spotter.reset_stream(ss)
            if not ready:
                break
            self.spotter.decode_streams(ready)

    @property
    def last_keyword(self) -> str:
        return self._last_keyword

    def reset(self) -> None:
        """重置主流与占位流（关键：两者都必须重建，否则批量解码状态错乱）。"""
        if self.spotter is not None:
            self.stream = self.spotter.create_stream()
            self._dummy = self.spotter.create_stream()
            self._last_keyword = ""
