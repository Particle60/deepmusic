#!/usr/bin/env bash
# 在 Linux 开发板上配置 ALSA 混音（dmix/dsnoop），让多进程共享声卡。
# 本脚本自包含：配置模板内嵌，无需依赖仓库里的 deploy/asound.conf。
#
# 背景：
#   裸 ALSA（无 /etc/asound.conf、无 PulseAudio）时，声卡默认是"独占"的：
#   - 音乐播放 mpv 正在播 → 提示音 mpv 打开输出失败 → 提示音无声
#   - 麦克风 arecord 与 播放 也会互相干扰
#   现象：只有"开机成功"（此时还没播音乐/没开麦克风）能响，之后全部无声。
#
# 用法（在板上）：
#   sudo bash setup_alsa.sh             # 自动检测声卡并写入 /etc/asound.conf
#   sudo bash setup_alsa.sh --dry       # 只打印将要写入的配置，不实际写入
#
# 前提：已装 alsa-utils（aplay/arecord）。板上音频驱动正常（speaker-test 能出声）。

set -euo pipefail

DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

# ---------- 1. 检测播放/采集设备 ----------
if ! command -v aplay >/dev/null; then
    echo "!! 未找到 aplay，请先安装 alsa-utils" >&2
    exit 1
fi

# 取第一块声卡：如 "card 0: nanopi2audio [nanopi2-audio]"
PLAY_CARD_LINE="$(aplay -l 2>/dev/null | grep -E '^card ' | head -1 || true)"
if [ -z "$PLAY_CARD_LINE" ]; then
    echo "!! 未检测到播放声卡（aplay -l 为空）" >&2
    exit 1
fi
CARD_NUM="$(echo "$PLAY_CARD_LINE" | sed -E 's/card ([0-9]+):.*/\1/')"
echo "检测到播放声卡: $PLAY_CARD_LINE"

# ---------- 2. 生成 /etc/asound.conf（模板内嵌，自动替换声卡编号） ----------
DEST="/etc/asound.conf"

CONF="$(
    sed -E \
        -e "s/pcm \"hw:0,0\"/pcm \"hw:${CARD_NUM},0\"/g" \
        -e "s/card 0/card ${CARD_NUM}/g" \
        <<'ASOUND_TEMPLATE'
# 由 setup_alsa.sh 自动生成：让多个程序（音乐 mpv / 提示音 mpv / arecord 麦克风）
# 共享同一块声卡，避免裸 ALSA 独占导致"提示音无声 / 设备被抢"。
# dmix 播放合路、dsnoop 采集分路、asym 组成默认设备。
pcm.dmix0 {
    type dmix
    ipc_key 5678293
    slave {
        pcm "hw:0,0"        # 声卡编号由脚本自动替换
        rate 48000
        channels 2
        period_size 1024
        buffer_size 8192
    }
}

pcm.dsnoop0 {
    type dsnoop
    ipc_key 5678294
    slave {
        pcm "hw:0,0"
        rate 48000
        channels 2
    }
}

pcm.!default {
    type asym
    playback.pcm "plug:dmix0"
    capture.pcm "plug:dsnoop0"
}

ctl.!default {
    type hw
    card 0
}
ASOUND_TEMPLATE
)"

echo "========== 将要写入 $DEST =========="
echo "$CONF"
echo "===================================="

if [ "$DRY" = "1" ]; then
    echo "（--dry 模式，未写入）"
    exit 0
fi

echo "$CONF" | sudo tee "$DEST" >/dev/null
echo "已写入 $DEST"

# ---------- 3. 验证 ----------
# 注意：不要用 ALSA_CONFIG_PATH 指到单个文件——那样会丢掉 /usr/share/alsa/alsa.conf
# （里面定义了 plug/dmix 等插件的默认别名），导致 type plug 解析不到、报 ENOENT(-2)。
# 验证应走系统默认搜索路径（会先读 /etc/asound.conf 再读标准配置），与应用(mpv)一致。
echo "== 验证 1：直通硬件设备（确认驱动正常） =="
speaker-test -D "hw:${CARD_NUM},0" -c 2 -t sine -l 1 -p 2 -r 48000 2>&1 | tail -2

echo "== 验证 2：默认设备走混音（应用实际用的路径） =="
speaker-test -D default -c 2 -t sine -l 1 -p 2 -r 48000 2>&1 | tail -2

# 用两个并行的 speaker-test 验证混音（dmix 生效则两者都不报"设备忙"）
speaker-test -D default -c 2 -t sine -l 1 -p 2 -r 48000 >/dev/null 2>&1 &
P1=$!
speaker-test -D default -c 2 -t sine -l 1 -p 3 -r 48000 >/dev/null 2>&1 &
P2=$!
wait $P1; R1=$?
wait $P2; R2=$?
if [ "$R1" = "0" ] && [ "$R2" = "0" ]; then
    echo "✅ 混音验证通过：两个播放进程可同时出声"
else
    echo "⚠️ 混音验证未完全通过（R1=$R1 R2=$R2），请检查 /etc/asound.conf 与声卡驱动"
fi

echo
echo "完成。现在音乐播放 / 提示音 / 麦克风可共享声卡。"
echo "如需恢复独占行为：sudo rm -f $DEST"
