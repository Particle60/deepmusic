#!/usr/bin/env bash
# 功耗采样（参考）——按板卡实际电源节点调整
# 用法: 手动在 5V 输入端接 USB 电流表，或运行本脚本采样 sysfs 电源节点
set -euo pipefail

echo "建议测量三个状态："
echo "  1) 播放中"
echo "  2) 待命（只跑 VAD+唤醒词）"
echo "  3) 深度休眠（suspend + 唤醒协处理器）"

# 示例：读取 sysfs 电池/电源节点（无则跳过）
for node in /sys/class/power_supply/*/; do
  [ -e "${node}current_now" ] && echo "current_now ($(basename "$node")): $(cat "${node}current_now") µA"
done

echo "提示：也可用 powertop 查看功耗；待机省电调优见 开发计划.md 第 8 节。"
