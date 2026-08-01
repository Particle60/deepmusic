"""WAV 回放：用语音样本走通 唤醒→识别→解析 链路（无麦克风）。"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.asr.engine import AsrEngine  # noqa: E402
from app.asr.wake import WakeWordDetector  # noqa: E402
from app.audio.fake_mic import FakeMicReader  # noqa: E402
from app.audio.pcm import pcm_bytes_to_float32  # noqa: E402
from app.commands.parser import parse_command  # noqa: E402
from app.config import Config  # noqa: E402

CHUNK = 3200  # 100ms @16k/16bit/mono


def run(wav_path: str, model_dir: str, kws_dir: str, no_wake: bool = False) -> int:
    cfg = Config.load()
    asr = AsrEngine(model_dir or cfg.resolve_model_dir(cfg.asr.model_dir),
                    sample_rate=cfg.audio.sample_rate)
    if not asr.load():
        print("ASR 模型加载失败，请检查 models/ 目录")
        return 1
    wake = None
    if not no_wake:
        wake = WakeWordDetector(kws_dir or cfg.resolve_model_dir(cfg.asr.kws_model_dir),
                                sample_rate=cfg.audio.sample_rate)
        if not wake.load():
            print("KWS 模型加载失败，将跳过唤醒词")
            wake = None

    mic = FakeMicReader(wav_path, chunk_bytes=CHUNK)
    mic.open()
    woken = bool(no_wake)
    result = ""
    try:
        # 整段读入内存（音频通常很短）
        pcm_all = b""
        while True:
            chunk = mic.read_chunk(CHUNK)
            if not chunk or all(b == 0 for b in chunk):
                break
            pcm_all += chunk
        samples = pcm_bytes_to_float32(pcm_all)
        # 追加 0.6s 尾静音，模拟说完话后的停顿，让模型识别完整句子
        samples = np.concatenate(
            [samples, np.zeros(int(0.6 * cfg.audio.sample_rate), dtype=np.float32)]
        )
        if not woken and wake is not None:
            wake.accept_waveform(samples)
            wake.finalize()  # 补尾静音+结束，促使关键词解码完成
            if wake.last_keyword:
                print("[唤醒] 命中唤醒词:", wake.last_keyword)
                woken = True
        if woken:
            asr.accept_waveform(samples)
        asr.finish()
        result = asr.get_text()
        print(f"[识别] {result}")
        cmd = parse_command(result)
        print(f"[意图] {cmd.intent} {cmd.args}")
        return 0
    finally:
        mic.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="用 WAV 回放测试 唤醒→识别→解析 链路")
    ap.add_argument("wav", help="16kHz/16bit/mono 中文指令 WAV")
    ap.add_argument("--model", default="", help="ASR 模型目录（默认用 config.yaml）")
    ap.add_argument("--kws", default="", help="KWS 模型目录")
    ap.add_argument("--no-wake", action="store_true", help="跳过唤醒词，直接识别")
    args = ap.parse_args()
    return run(args.wav, args.model, args.kws, args.no_wake)


if __name__ == "__main__":
    sys.exit(main())
