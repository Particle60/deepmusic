#!/usr/bin/env python3
"""用 KWS 模型自带的 text2token 生成自定义唤醒词关键词文件。

用法:
    python3 scripts/make_kws_keywords.py "你好小智" "小智小智"

输出: 覆盖写 <kws模型目录>/keywords.txt（KWS 加载时优先使用根目录的 keywords.txt）

说明: 自动判断 tokens-type —— 若模型目录有 en.phone 用 phone+ppinyin（中英混合），
否则用 ppinyin（纯拼音，wenetspeech 中文模型）。
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config  # noqa: E402
from app.asr.wake import _find_model_dir  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 scripts/make_kws_keywords.py 唤醒词1 [唤醒词2 ...]")
        return 1
    wake_words = sys.argv[1:]
    cfg = Config.load()
    md = _find_model_dir(cfg.resolve_model_dir(cfg.asr.kws_model_dir))
    tok = os.path.join(md, "tokens.txt")
    lex = os.path.join(md, "en.phone")
    if not os.path.exists(tok):
        print("找不到 KWS 模型 tokens.txt，请先下载模型到 models/kws/")
        return 1

    import sherpa_onnx  # type: ignore

    wake_words = [w.replace(" ", "_") for w in wake_words]
    if os.path.exists(lex):
        token_lists = sherpa_onnx.text2token(
            wake_words, tokens=tok, tokens_type="phone+ppinyin", lexicon=lex
        )
    else:
        token_lists = sherpa_onnx.text2token(
            wake_words, tokens=tok, tokens_type="ppinyin"
        )
    out_path = os.path.join(md, "keywords.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        for w, tokens in zip(wake_words, token_lists):
            f.write(" ".join(tokens) + " @" + w + "\n")
    print("已生成:", out_path)
    with open(out_path, "r", encoding="utf-8") as f:
        print(f.read())
    return 0


if __name__ == "__main__":
    sys.exit(main())
