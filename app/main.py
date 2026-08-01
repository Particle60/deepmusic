"""入口：默认控制台开发模式；支持 --replay / --voice。"""
from __future__ import annotations

import argparse
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config  # noqa: E402


def setup_logging(cfg: Config) -> None:
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]
    if cfg.logging.file:
        handlers.append(logging.FileHandler(cfg.logging.file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="离线语音音乐播放器")
    ap.add_argument("--console", action="store_true", help="控制台开发模式（文本注入，无需麦克风/模型）")
    ap.add_argument("--replay", metavar="WAV", default="", help="回放 WAV 语音样本测试识别链路")
    ap.add_argument("--no-wake", action="store_true", help="配合 --replay：跳过唤醒词直接识别")
    ap.add_argument("--voice", action="store_true", help="语音模式（需麦克风 + ASR/KWS 模型）")
    args = ap.parse_args()

    cfg = Config.load()
    setup_logging(cfg)

    if args.replay:
        from app.cli import replay

        return replay.run(args.replay, "", "", no_wake=args.no_wake)
    if args.voice:
        from app.cli import voice

        return voice.main(cfg)
    # 默认进入控制台开发模式
    from app.cli import console

    return console.main(cfg)


if __name__ == "__main__":
    sys.exit(main())
