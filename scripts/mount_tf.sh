#!/usr/bin/env bash
# 自动挂载 TF 卡（支持随意更换）——不用 fstab 的 UUID（换卡就要改），
# 而是启动时自动探测 TF 卡分区并挂载到 /mnt/sd。
#
# 用法：
#   sudo bash scripts/mount_tf.sh          # 探测并挂载
#   sudo bash scripts/mount_tf.sh --check  # 仅检查当前状态，不挂载
#
# 支持格式：vfat(FAT32) / exfat / ext4。其余格式会提示但不报错退出。
# 挂载权限：FAT/exFAT 用 uid=1000,gid=1000,umask=000（pi 可读写）；
#           ext4 挂为读写并 chown 给 1000。
#
# 已挂载时：若已挂到 /mnt/sd 直接返回 0；若挂到别处先忽略（不抢）。

set -uo pipefail
MOUNT_POINT="/mnt/sd"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

log() { echo "[mount_tf] $*"; }

# ---------- 1. 已挂载则跳过 ----------
if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    log "已在 $MOUNT_POINT 挂载，跳过。"
    exit 0
fi

# ---------- 2. 探测 TF 卡分区 ----------
# 优先：mmcblk1*（TF 卡槽典型设备名，NanoPi-S2 上是 mmcblk1）
# 兜底：扫描 lsblk，找"未挂载的磁盘上的第一个分区"，且该磁盘不是根系统盘
CANDIDATE=""
for d in /dev/mmcblk1p1 /dev/mmcblk0p4 /dev/sda1 /dev/sdb1; do
    [ -b "$d" ] && CANDIDATE="$d" && break
done

if [ -z "$CANDIDATE" ]; then
    # 通用探测：找有分区、且分区未挂载、且磁盘不是根所在的盘
    ROOT_DISK="$(findmnt -no SOURCE / | sed -E 's#(/dev/[a-z]+).*#\1#')"
    while read -r name type; do
        [ "$type" != "part" ] && continue
        # 若这个分区或其所在磁盘正在使用（根/已挂载），跳过
        if [ -n "$ROOT_DISK" ] && [[ "/dev/$name" == "$ROOT_DISK"* ]]; then
            continue
        fi
        if findmnt -rn -S "/dev/$name" >/dev/null 2>&1; then
            continue
        fi
        CANDIDATE="/dev/$name"
        break
    done < <(lsblk -rno NAME,TYPE)
fi

if [ -z "$CANDIDATE" ]; then
    log "未找到未挂载的 TF 卡分区。"
    [ "$CHECK" = "1" ] && exit 1 || exit 0
fi

log "探测到分区: $CANDIDATE"

# ---------- 3. 识别文件系统 ----------
FS_TYPE="$(blkid -o value -s TYPE "$CANDIDATE" 2>/dev/null)"
[ -z "$FS_TYPE" ] && FS_TYPE="auto"
log "文件系统: $FS_TYPE"

case "$FS_TYPE" in
    vfat|exfat)
        OPTS="defaults,uid=1000,gid=1000,umask=000,fmask=113,dmask=002"
        ;;
    ext2|ext3|ext4)
        OPTS="defaults,noatime"
        ;;
    *)
        log "不支持的文件系统: $FS_TYPE（支持 vfat/exfat/ext4）。"
        [ "$CHECK" = "1" ] && exit 1 || exit 0
        ;;
esac

if [ "$CHECK" = "1" ]; then
    log "（--check）将挂载: $CANDIDATE ($FS_TYPE) → $MOUNT_POINT"
    exit 0
fi

# ---------- 4. 挂载 ----------
mkdir -p "$MOUNT_POINT"
if ! mount -o "$OPTS" "$CANDIDATE" "$MOUNT_POINT" 2>/tmp/mount_tf.err; then
    log "挂载失败: $(cat /tmp/mount_tf.err)"
    exit 1
fi

# ext4 再给 pi 写权限
if [[ "$FS_TYPE" == ext* ]]; then
    chown 1000:1000 "$MOUNT_POINT" 2>/dev/null || true
fi

log "✅ 已挂载 $CANDIDATE → $MOUNT_POINT"
ls "$MOUNT_POINT" | head -5 | sed 's/^/    /'
exit 0
