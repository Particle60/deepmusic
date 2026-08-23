# 离线语音音乐播放器 · 使用手册

> 在 Linux 开发板上实现"唤醒词 + 离线中文语音指令 → 播放本地歌曲 / 管理播放列表"的应用。
> 全程离线，不依赖网络。

---

## 1. 快速上手

### 1.1 启动

在项目根目录（`/Users/jijiang/projects/dajie`）执行：

```bash
# 语音模式（需麦克风 + 模型）——正常使用方式
.venv/bin/python app/main.py --voice

# 开发模式：文本输入模拟语音指令（无需麦克风）
.venv/bin/python app/main.py --console

# 开发模式 + 真实播放器：输入指令能听到音乐（macOS/Linux 都行，需安装 mpv）
VMP_REAL_PLAYER=1 .venv/bin/python app/main.py --console

# 回放 WAV 语音样本，验证 识别→解析 链路
.venv/bin/python app/main.py --replay test_data/播放青花瓷.wav --no-wake
```

> **真实播放器**：默认控制台用假播放器（不出声，便于测试）。设 `VMP_REAL_PLAYER=1` 会用 mpv 真正播放。
> 播放输出由 `config/config.yaml` 的 `audio.ao` 决定：留空=自动检测（开发机）、`alsa`（板子）、`null`（无声）。

启动后，先听到 **"开机成功"** 提示音，表示程序已就绪、开始监听唤醒词。

### 1.2 命令行参数

| 参数 | 说明 |
|------|------|
| `--voice` | 语音模式（默认监听唤醒词 → 指令） |
| `--console` | 开发控制台，纯文本注入 |
| `--replay <wav>` | 回放 WAV 验证识别链路 |
| `--no-wake` | 配合 `--replay`，跳过唤醒词直接识别 |

### 1.3 环境变量

| 变量 | 说明 |
|------|------|
| `VMP_MUSIC_DIR` | 覆盖音乐目录（优先级最高） |
| `VMP_REAL_PLAYER=1` | 控制台模式用真 mpv 播放（听到声音） |

---

## 2. 基本使用（语音交互流程）

### 2.1 完整流程

```
你说唤醒词 → 播放器说"你好" → 你说指令 → 执行（静默或播报）
```

1. **唤醒**：对麦克风说唤醒词（当前为 `小度小度`），播放器回复 **"你好"**，进入听指令状态。
2. **下指令**：接着说出指令，如 `播放歌曲七里香`。
3. **执行**：识别成功则执行；失败播放器会说"听不懂"并恢复音乐。

> 小贴士：唤醒后需等播放器说完"你好"再下指令；指令尽量说完整、语速适中。

### 2.2 唤醒词（可自定义）

当前唤醒词：**`小度小度`**（由 KWS 模型目录 `models/kws/.../keywords.txt` 决定）。

**自定义唤醒词**（用脚本生成，自动转拼音 token）：

```bash
# 生成唤醒词，可同时指定多个
.venv/bin/python scripts/make_kws_keywords.py "小度小度" "小智小智"
# 会覆盖写 KWS 模型目录下的 keywords.txt
```

说明：
- 关键词文件加载优先级：`config/config.yaml` 的 `asr.keywords_file` 显式指定 > 模型目录 `keywords.txt` > `test_wavs/test_keywords.txt`
- 脚本自动判断 token 类型（模型有 `en.phone` 用 phone+ppinyin，否则用纯 ppinyin）
- ⚠️ 新词（模型训练时未见过）唤醒灵敏度可能略低，建议用叠词（如"小度小度"）更易命中
- 想让多个唤醒词同时生效，把需要的词一次全部传给脚本

---

## 3. 语音指令全集

> 指令说法可在 `config/commands.yaml` 中自由增改，**无需改代码**。

### 3.1 播放

| 说法示例 | 意图 | 说明 |
|----------|------|------|
| `播放歌曲七里香` | play_song | 播放指定歌曲（拼音模糊匹配） |
| `播放歌曲《七里香》` | play_song | 带书名号更易识别 |
| `播放歌单跑步` | play_playlist | 播放指定歌单 |
| `播放所有歌曲` | play_playlist | 播放全部歌曲 |
| `播放第3首` | play_index | 播放当前队列第 N 首 |

> 播放歌曲需带"歌曲/音乐/歌"前缀（如 `播放歌曲X`），避免与"播放歌单"混淆。

### 3.2 播放控制

| 说法示例 | 意图 |
|----------|------|
| `下一首` / `下一曲` / `下一首歌` / `播放下一首` / `换一首` / `切到下一首` | next |
| `上一首` / `上一曲` / `播放上一首` / `回到上一首` | prev |
| `暂停` / `暂停播放` / `先暂停` / `停一下` / `先停一下` | pause |
| `继续` / `接着播` / `接着放` / `继续播放` / `开始播放` / `播放` | resume |
| `停止` / `停止播放` / `停播` / `别放了` / `关机` / `关音乐` / `停止音乐` | stop |

> 说明：`关机` / `关音乐` 语义与 `停止` 相同（停止播放，不会真的关闭系统）。

### 3.3 播放模式

| 说法示例 | 模式 |
|----------|------|
| `随机播放` / `随机播` / `乱序播放` / `打乱` / `洗牌` / `随机放` | 随机播放 |
| `顺序播放` / `顺序播` / `按顺序` / `顺序放` | 顺序播放 |
| `单曲循环` / `单曲播` / `循环这首` / `循环单曲` / `这首循环` | 单曲循环 |
| `列表循环` / `全部循环` / `循环播放` / `连播` / `循环` | 列表循环 |

> 切换模式后播放器会播报确认，如"已切换为随机播放"；切换模式不会打断当前歌曲。

### 3.4 音量

| 说法示例 | 效果 |
|----------|------|
| `音量调到60` / `音量调到60` / `把声音调到60` | 音量设为 60 |
| `把声音调到六十` / `把音量调到一百` / `把声音调到五` | 支持中文数字 |
| `音量加大` / `把声音调大点` / `声音调大` / `大声点` / `调高音量` | 音量 +10 |
| `音量减小` / `把声音调小点` / `声音调小` / `小声点` / `调低音量` | 音量 -10 |

> 每次调音量后播放器播报当前音量（中文数字，如"音量六十"）。

### 3.5 查询

| 说法示例 | 效果 |
|----------|------|
| `现在放的是什么歌` / `现在播放的是什么` / `正在播放` | 播报当前歌曲名 |
| `现在歌单是什么` / `现在歌单是哪个` | 播报当前所在歌单 |
| `当前播放模式是什么` / `播放模式是什么` / `现在什么模式` | 播报当前播放模式 |
| `列出歌单` / `有哪些歌单` / `查看所有歌单` | 列出所有歌单 |

### 3.6 刷新歌单

| 说法示例 | 效果 |
|----------|------|
| `更新歌单` / `刷新歌单` / `重新扫描` / `更新音乐` | 不重启程序：重新扫描音乐库 + 重载歌单（含新增/删除歌单） |

> 往 SD 卡拷入/删除歌曲或歌单后，说"更新歌单"即可让 `所有歌曲` 和全部歌单同步。

### 3.7 容错说明

- 指令识别不清时会播报 **"听不懂"** 并恢复音乐。
- 歌曲名匹配不上会播报 **"歌曲不存在"**；歌单匹配不上会播报 **"歌单《xx》为空或不存在"**。
- 对同音字/丢字/叠字（如"随机播"≈"随机播放"）做了模糊匹配兜底。

---

## 4. 音乐库与歌单

### 4.1 音乐目录

- 配置：`config/config.yaml` → `music.dir`
- 默认：`music/music`（项目根下）
- 上板后改为 SD 卡挂载路径，如 `/mnt/sd/Music`
- 支持子目录（如 `周杰伦/`、`金曲/`），扫描时自动递归
- 支持格式：`.mp3` `.flac` `.wav` `.m4a` `.ogg` `.aac`

### 4.2 歌单

- 歌单以 `.m3u` 文件存放在 `music/playlists/`（与歌曲目录同级）
- 启动/指令时自动扫描发现
- **`所有歌曲`** 为内置歌单（全部歌曲），不可删除
- 歌单内路径为**相对音乐目录**的相对路径，如：
  ```
  #EXTM3U
  晴天.wav
  周杰伦/周杰伦[2004.08.03][七里香]AAC 256K/01 我的地盘.m4a
  ```

### 4.3 手动配置歌单示例

`music/playlists/跑步.m3u`：
```
#EXTM3U
晴天.wav
周杰伦/周杰伦[2004.08.03][七里香]AAC 256K/01 我的地盘.m4a
周杰伦/周杰伦[2004.08.03][七里香]AAC 256K/02 七里香.m4a
```

---

## 5. 配置说明（`config/config.yaml`）

| 配置段 | 字段 | 说明 |
|--------|------|------|
| `music` | `dir` | 音乐目录（相对项目根或绝对路径） |
| `music` | `extensions` | 扫描的音频扩展名 |
| `music` | `playlists_dir` | 歌单目录（留空=音乐目录下 playlists） |
| `audio` | `mic_device` | 麦克风设备名（板子 ALSA: `-D` 设备名） |
| `audio` | `mic_backend` | 麦克风后端：`""`=自动(linux→alsa,其他→sounddevice) |
| `audio` | `ao` | 播放输出：`""`=mpv自动检测 / `null`=静音 / `alsa`=板子 |
| `audio` | `volume` | 初始音量 |
| `asr` | `model_dir` | 中文流式识别模型路径 |
| `asr` | `kws_model_dir` | 唤醒词 KWS 模型路径 |
| `asr` | `keywords_file` | 唤醒词文件（留空=用模型自带） |
| `tts` | `enabled` | 是否启用离线 TTS 播报 |
| `tts` | `model_dir` | 离线 TTS 模型路径（melo） |
| `tts` | `length_scale` | 语速（越小越快） |
| `tts` | `volume` | 提示音音量 (0-100) |
| `vad` | `energy_threshold` | 静音门控阈值（越大越不易误触发） |
| `vad` | `silence_timeout_ms` | 判定一句话结束的静音时长 |
| `state` | `wake_timeout_ms` | 唤醒后等待指令超时 |
| `state` | `wake_feedback_ms` | 唤醒提示音时长（期间丢弃麦克风音频） |
| `player` | `mode` | 默认播放模式（order/repeat_all/repeat_one/shuffle） |
| `logging` | `level` | 日志级别 |

---

## 6. 语音反馈（TTS 播报）

- 播报内容：开机成功 / 你好 / 已切换为X播放 / 音量X / 听不懂 / 歌曲不存在 等
- 后端：**sherpa-onnx 离线中文 TTS**（melo，44100Hz），完全离线
- 音色切换：`config/config.yaml` → `tts.model_dir` 换模型，`speaker_id` 换说话人（多说话人模型）
- 无模型时自动回退：macOS `say` / Linux `espeak-ng`

---

## 7. 常见问题

### 7.1 唤醒后说"你好"听不到？

melo 对单字/低振幅词合成音量小，程序已做**归一化增益**（峰值拉到 0.9）。若仍偏小，调大 `config/config.yaml` 的 `tts.volume`。

### 7.2 唤醒词命不中？

- 确认当前唤醒词（`小度小度`）或已按 2.2 节自定义
- 新自定义词灵敏度偏低时：改回叠词，或用模型内置词（小爱同学/你好军哥等）
- macOS `say` TTS 合成语音无法触发 KWS（音色差异），**真人语音可正常唤醒**
- 环境噪音大时可调 `vad.energy_threshold`

### 7.3 指令总说"听不懂"？

- 确认带了"歌曲"前缀：`播放歌曲X` 而非 `播放X`
- 语速适中、说完再停
- 可在 `config/commands.yaml` 增加同义说法

### 7.4 想听到音乐出声？

- 安装 mpv：`brew install mpv`（macOS）/ `apt install mpv`（板子）
- 语音模式 `ao` 留空自动检测；开发控制台加 `VMP_REAL_PLAYER=1`

---

## 8. 上板部署提示

- 音乐目录改为 SD 卡路径：`config/config.yaml` → `music.dir: "/mnt/sd/Music"`
- 播放输出改为 ALSA：`audio.ao: "alsa"`
- 麦克风后端自动用 ALSA（Linux）
- systemd 自启示例见 `deploy/`，依赖安装见 `scripts/install_deps.sh`

### 8.1 依赖安装（多架构）

`scripts/install_deps.sh` 同时支持 **ARM Linux（aarch64）** 与 **x86_64 Linux**。

**有网（板子上直接装）：**
```bash
./scripts/install_deps.sh          # 自动检测当前架构安装
```

**离线（先在电脑上准备，一次覆盖两种架构）：**
```bash
# 电脑上：下载 arm + x86_64 全部 wheel（默认板子 python 3.11）
./scripts/install_deps.sh --download-only --arch all --offline-dir ./offline
# 只需一种架构：
./scripts/install_deps.sh --download-only --arch aarch64 --offline-dir ./offline
./scripts/install_deps.sh --download-only --arch x86_64 --offline-dir ./offline

# 把 ./offline 目录拷到板子，然后：
./scripts/install_deps.sh --offline-dir ./offline   # pip 自动挑匹配架构的 wheel
```

> 其他参数：`--pip-only` 跳过系统包；`TARGET_PY=3.10` 指定板子 python 版本（默认 3.11）。

### 8.2 部署清单

| 步骤 | 说明 |
|------|------|
| 依赖 | `install_deps.sh`（见 8.1） |
| 模型 | 拷贝 `models/asr`、`models/kws`、`models/tts_melo`（平台无关 ONNX） |
| 配置 | `music.dir` 指向 SD 卡、`audio.ao: "alsa"` |
| 硬件 | 麦克风（ALSA）、喇叭（mpv `--ao=alsa`） |
| 自启 | `deploy/voice-music-player.service` → systemd |

---

## 9. 项目结构

```
dajie/
├── config/               # 配置目录
│   ├── config.yaml       # 主配置（音乐/音频/ASR/TTS/VAD/状态/播放器）
│   └── commands.yaml     # 语音指令配置（可自由增改说法）
├── app/
│   ├── main.py           # 入口（--console / --replay / --voice）
│   ├── state_machine.py  # 待机→唤醒→指令 状态机
│   ├── audio/            # 麦克风/扬声器/TTS 抽象
│   ├── asr/              # sherpa-onnx 识别/唤醒/VAD
│   ├── music/            # 音乐库/歌单/拼音匹配/播放器
│   ├── commands/         # 文本→意图→操作
│   └── cli/              # 控制台/回放/语音模式
├── assets/tts_cache/     # 预合成提示短语音频（仓库内，随项目分发）
├── tests/                # 单元测试（72 个，无硬件依赖）
├── scripts/              # 依赖安装/测试素材/唤醒词生成/功耗脚本
├── models/               # 模型目录（asr / kws / tts_melo）
├── music/                # 音乐目录
│   ├── music/            # 歌曲文件（download/周杰伦/金曲）
│   └── playlists/        # 歌单（.m3u，与歌曲目录同级）
├── state/                # 播放状态持久化
└── deploy/               # 上板部署文件
```
