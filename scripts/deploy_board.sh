#!/usr/bin/env bash
# 一键部署到 Linux 开发板（需在板子上运行，或 ssh 远程执行）
# 用法: ./scripts/deploy_board.sh <项目路径> [板子用户@板子IP]
# 示例: ./scripts/deploy_board.sh /opt/voice-music-player pi@192.168.1.50
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${1:-/opt/voice-music-player}"
TARGET="${2:-}"

echo "==> 部署源: $SRC -> $APP_DIR"
if [ -n "$TARGET" ]; then
  echo "==> 通过 ssh 部署到 $TARGET"
  rsync -av --exclude '.venv' --exclude '__pycache__' --exclude 'music' "$SRC/" "$TARGET:$APP_DIR/"
  ssh "$TARGET" "cd '$APP_DIR' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && sudo cp deploy/voice-music-player.service /etc/systemd/system/ && sudo systemctl daemon-reload && echo '安装完成，请修改 service 里的 User 后: sudo systemctl enable --now voice-music-player'"
else
  echo "==> 本机部署（未指定 ssh 目标）"
  echo "  1) 把项目放到 $APP_DIR"
  echo "  2) 创建 venv 并装依赖: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  echo "  3) sudo cp $APP_DIR/deploy/voice-music-player.service /etc/systemd/system/"
  echo "  4) 修改 service 里的 User/路径 后: sudo systemctl enable --now voice-music-player"
fi
