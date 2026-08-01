#!/usr/bin/env bash
# 生成测试音乐与语音指令样本（需要 ffmpeg）
# 用法: ./scripts/gen_test_audio.sh [输出目录]
set -euo pipefail

OUT="${1:-./test_data}"
mkdir -p "$OUT"

echo "==> 生成测试歌曲（不同频率正弦波）"
for i in 1 2 3 4 5; do
  freq=$((220 * i))
  ffmpeg -y -f lavfi -i "sine=frequency=${freq}:duration=5" \
    -codec:a libmp3lame "$OUT/track_${i}.mp3" >/dev/null 2>&1
done

echo "==> 说明"
echo "  测试音乐已生成到 $OUT"
echo "  语音指令样本：在电脑上用录音或 TTS 生成 16kHz/16bit/单声道 WAV，"
echo "  如“播放 青花瓷.wav”，拷入后运行: python3 app/main.py --replay <样本.wav>"
echo "完成。"
