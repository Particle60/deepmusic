# 开发板提示音丢失排查记录

> 日期：2026-08-25　设备：NanoPi-S2（S5P6818 / ES8316 codec）　系统：Linux（裸 ALSA，无 PulseAudio）
> 结论：**根因是裸 ALSA 声卡"独占"（无混音），导致音乐播放/麦克风占住声卡后，提示音打不开输出设备**。配置 dmix 混音后恢复。

---

## 1. 现象

- **macOS / Intel x86** 上一切正常：开机提示音、唤醒回应、指令反馈都能听到。
- **开发板**上：只有 **"开机成功"** 能播，之后**所有提示音**（你好 / 已暂停 / 已停止 / 听不懂…）全部无声。
- 板子 `/etc/asound.conf` 不存在（裸 ALSA）。

---

## 2. 根因

裸 ALSA（无 PulseAudio、无 `/etc/asound.conf`）时，声卡默认是**独占**的：

- "开机成功"在**播放音乐前**发出 → 声卡空闲 → 能响 ✅
- 之后音乐播放 mpv / 麦克风采集占住声卡 → 提示音再开输出 → **打不开设备 → 无声** ❌

macOS/Intel 不暴露，是因为有 coreaudio/pulseaudio 混音兜底，多进程可同时发声；裸 ALSA 板子没有混音，冲突直接暴露。

A/B 验证也证实了这一点：回滚掉其他改动后提示音仍正常，**只要配置了 dmix 混音，提示音即恢复**。

---

## 3. 修复：配置 ALSA 混音

用 `dmix`（播放合路）/ `dsnoop`（采集分路）/ `asym`（组合默认设备）让多进程共享声卡。

### 3.1 一键脚本（推荐）

```bash
sudo bash scripts/setup_alsa.sh          # 自动检测声卡编号，写入 /etc/asound.conf 并验证混音
sudo bash scripts/setup_alsa.sh --dry    # 只打印将要写入的配置，不实际写入
```

脚本自包含（模板内嵌，无需依赖其他文件），会自动：
1. 检测声卡编号（`aplay -l`）
2. 生成 `/etc/asound.conf`
3. 用两个并行 `speaker-test` 验证混音（关键测试：两个进程同时出声不报"设备忙"）

### 3.2 生成的 `/etc/asound.conf` 结构

```
pcm.dmix0    # dmix：播放输出合路，多进程可同时写
pcm.dsnoop0  # dsnoop：麦克风输入分路
pcm.!default # asym：播放走 dmix、采集走 dsnoop
```

---

## 4. 验证结果（NanoPi-S2 实测）

```
== 验证 1：直通硬件设备 ==      （-32 Broken pipe 为 speaker-test 单次循环正常收尾）
== 验证 2：默认设备走混音 ==    ✅
✅ 混音验证通过：两个播放进程可同时出声
```

- 写入 `/etc/asound.conf` 后，音乐播放 / 提示音 / 麦克风可共享声卡。
- 重启应用后：**开机提示音、音乐播放中的"你好"、指令反馈全部恢复正常。**

---

## 5. 排查口诀（下次遇到"无声"先查这些）

1. **确认是播放链路还是识别链路**：提示音=Speaker→播放器；识别=mic→KWS/ASR。先分清。
2. **检查混音**：`cat /etc/asound.conf`；`speaker-test -D default` 能出声且两个并发不报"设备忙"即正常。
3. **看日志**：`/tmp/vmp_tts_err.log` 是提示音播放的真实 stderr；应用日志看 `[speaker]` 行。
4. **`-2 ENOENT` 陷阱**：验证 ALSA 配置时**不要用 `ALSA_CONFIG_PATH` 指向单文件**，否则会丢掉系统插件定义；用系统默认路径验证。

---

## 6. 涉及文件

| 文件 | 说明 |
|------|------|
| `deploy/asound.conf` | ALSA 混音模板（参考） |
| `scripts/setup_alsa.sh` | 自包含安装脚本（模板内嵌，自动检测声卡、写入并验证混音） |
| `README.md` | 部署章节补充混音配置步骤 |
