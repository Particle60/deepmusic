#!/usr/bin/env bash
# 一键冒烟测试：无硬件/无模型，走通 扫描→播放→歌单→模式 全流程
# 用法: ./scripts/smoke_test.sh
# 说明: 使用项目根目录下的 music/ 文件夹作为歌曲目录
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

MUSIC_DIR="$ROOT/music"
if [ ! -d "$MUSIC_DIR" ] || [ -z "$(ls -A "$MUSIC_DIR")" ]; then
  echo "!! 音乐目录为空: $MUSIC_DIR"
  echo "!! 请放入音频文件，或运行: python3 -c \"import wave,struct,math,os; ...\" 生成测试音"
  exit 1
fi

echo "==> 使用音乐目录: $MUSIC_DIR"
echo "==> 运行控制台冒烟测试"
printf '!scan\n!all\n播放 青花瓷\n播放歌单 all\n创建歌单 跑步\n把 晴天 加入歌单 跑步\n!playlists\n随机播放\n下一首\n暂停\n继续\n音量调到 60\n现在放的是什么歌\n!status\n!q\n' \
  | VMP_MUSIC_DIR="$MUSIC_DIR" "$PY" "$ROOT/app/main.py" --console 2>/dev/null

ret=$?
echo "==> 冒烟测试结束，退出码: $ret"
exit $ret
