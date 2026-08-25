# NanoPi-S2 无声排查记录：ALSA 报 -25 ENOTTY

> 日期：2026-08-12　设备：NanoPi-S2（S5P6818）　内核：Linux 4.4.172　用户态：Ubuntu noble (24.04) armhf
> 结论：**不是硬件/驱动问题，是"新用户态 ALSA 库 + 老内核"的 ABI 不兼容**。已通过降级 alsa-lib 解决。

---

## 1. 现象

```bash
# 板载 ES8316 声卡
$ speaker-test -D plughw:0,0 -c 2 -t wav
Playback open error: -25,Inappropriate ioctl for device

# USB 耳机（Jabra EVOLVE 20）
$ speaker-test -D plughw:1,0 -c 2 -t wav
Playback open error: -25,Inappropriate ioctl for device
```

`aplay -l` 两个设备都能枚举到，但播放端全部报 `-25 (ENOTTY)`。

---

## 2. 排查链路

### 2.1 dmesg：驱动层是健康的

```bash
$ dmesg | grep -Ei 'es8316|asoc|snd|codec|i2s'
nexell-pcm nexell-pcm: snd pcm: register sound platform 'nexell-pcm'
nexell-i2s c0055000.i2s: ... master, iis mode, 48000hz ...
nx-simple-card sound: ES8316 HiFi <-> c0055000.i2s mapping ok
```

无 probe failed、无 ASoC 报错 → 板载 codec 驱动正常。

### 2.2 关键线索：两个无关设备同病

板载 I2S 声卡与 USB Audio 是完全独立的两条链路，**在同一个 ioctl 上报 ENOTTY**，说明问题出在它们共享的层：ALSA 用户态库 / 内核 snd 核心。

### 2.3 strace 锁定根因

```bash
$ strace -f -e trace=ioctl speaker-test -D hw:0,0 -c 2 -t wav 2>&1 | grep -Ei 'SNDRV|ENOTTY'
ioctl(4, SNDRV_CTL_IOCTL_CARD_INFO, ...) = 0
ioctl(4, SNDRV_PCM_IOCTL_INFO, ...)     = 0
ioctl(4, AGPIOC_INFO or SNDRV_PCM_IOCTL_PVERSION, ...) = 0
ioctl(4, AGPIOC_SETUP or SNDRV_PCM_IOCTL_TTSTAMP, ...) = 0
ioctl(4, _IOC(_IOC_READ|_IOC_WRITE, 0x41, 0x23, 0x88), ...) = -1 ENOTTY
```

解码 `0x41`(类='A',PCM) + `0x23`(nr=35) + `0x88`(136 字节)：
- nr=35 → **`SNDRV_PCM_IOCTL_SYNC_PTR`**（64 位结构体变体）
- 这族 64 位 time/帧 ioctl 是 **Linux 4.17 才加入**内核的
- 4.4 内核的 `snd_pcm_ioctl()` 不认识这些编号 → 对任何声卡一律返回 `ENOTTY`

### 2.4 版本确认：铁证

```bash
$ uname -a
Linux NanoPi-S2 4.4.172-s5p4418 #1 SMP ... armv7l armv7l armv7l GNU/Linux   # ← 2016 年内核

$ aplay --version
aplay: version 1.2.9 ...                                                     # ← noble(24.04) 的 t64 版

$ apt-cache policy libasound2
Installed: (none)                                                            # noble 里它改名叫 libasound2t64
```

**根因**：Ubuntu noble 用户态使用 **t64（64 位 time_t）构建**的 `libasound2t64`，默认走 64 位 PCM ioctl；4.4 老内核不支持 → 整卡 `ENOTTY`。

---

## 3. 解决方式：降级 alsa-lib 到非 t64（bullseye）版

```bash
# 1) 清理当前损坏状态
sudo dpkg --remove libasound2
sudo dpkg --remove --force-depends libasound2t64

# 2) 下载 bullseye 非 t64 版本（注意准确文件名）
wget http://ftp.debian.org/debian/pool/main/a/alsa-lib/libasound2_1.2.4-1.1_armhf.deb
wget http://ftp.debian.org/debian/pool/main/a/alsa-lib/libasound2-data_1.2.4-1.1_all.deb
wget http://ftp.debian.org/debian/pool/main/a/alsa-utils/alsa-utils_1.2.4-1_armhf.deb

# 3) 强装（t64 有 Breaks 冲突，需 --force-depends）
sudo dpkg -i --force-depends \
    libasound2_1.2.4-1.1_armhf.deb \
    libasound2-data_1.2.4-1.1_all.deb \
    alsa-utils_1.2.4-1_armhf.deb

# 4) 修复 dpkg 状态
sudo dpkg --configure -a

# 5) 验证
speaker-test -D plughw:0,0 -c 2 -t wav   # 出声 = 成功
```

> 易踩的坑：`libasound2-data` 是 `_all.deb`（架构无关），`alsa-utils` 版本号是 `1.2.4-1`（不是 `-1.1`）。

---

## 4. 后续注意事项

1. **不要再 `apt upgrade` 动 alsa 相关包**：`libasound2t64` 现处于 broken 状态，任何一次升级都可能把 t64 装回来，再次弄哑音频。
2. **长期运行建议重刷 FriendlyElec 官方镜像**：当前是"noble 用户态 + 4.4 内核"混搭，除音频外其他 t64 库/systemd/Python 还可能陆续踩坑。官方镜像是配套的，音频开箱即用。当前环境只当临时验证用。
3. **与项目的衔接**：音频通了之后，把 `config.yaml` 的 `audio.ao` 设为 `"alsa"`（或 `"alsa/plughw:0,0"`），再用 `arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1` 确认麦克风，即可进入"唤醒 → 识别 → 播放"真机联调。

---

## 5. 一句话总结

`-25 ENOTTY` 出现在**两个无关设备**上、且 dmesg 无驱动错误 → 不是硬件问题；
strace 显示挂在 **PCM 核心 ioctl（`SNDRV_PCM_IOCTL_SYNC_PTR64`）** → 是 ABI 问题；
`4.4 内核` + `noble t64 alsa-lib` → **用户态与内核版本不匹配**；
把 alsa-lib 降级回 bullseye 非 t64 版 → 解决。