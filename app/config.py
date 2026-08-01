"""配置加载：config.yaml + 环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class MusicConfig:
    dir: str = "/mnt/sd/Music"
    extensions: List[str] = field(
        default_factory=lambda: [".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac"]
    )
    playlists_dir: str = ""

    @property
    def resolved_playlists_dir(self) -> str:
        return self.playlists_dir or os.path.join(self.dir, "playlists")


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    mic_device: str = ""
    mic_backend: str = ""    # ""=自动(linux→alsa, 其他→sounddevice) / alsa / sounddevice
    ao: str = ""             # 留空 = mpv 自动检测音频输出；开发无硬件可设 "null"
    volume: int = 80


@dataclass
class AsrConfig:
    model_dir: str = "models/asr"
    kws_model_dir: str = "models/kws"
    keywords_file: str = ""     # 唤醒词文件；留空则用模型目录 keywords.txt → test_wavs/test_keywords.txt


@dataclass
class TtsConfig:
    enabled: bool = False        # 是否启用离线 TTS 播报
    model_dir: str = "models/tts/vits-icefall-zh-aishell3"
    speaker_id: int = 33         # 多说话人模型音色 id
    length_scale: float = 1.0    # 语速缩放（越小越快），单说话人模型用
    volume: int = 100            # 提示音播放音量 (0-100)


@dataclass
class VadConfig:
    energy_threshold: int = 120
    min_speech_ms: int = 100
    silence_timeout_ms: int = 800


@dataclass
class StateConfig:
    wake_timeout_ms: int = 8000        # 唤醒后等待指令的超时
    wake_feedback_ms: int = 700        # 唤醒提示音（"诶"）时长，期间丢弃麦克风音频避免被识别
    post_wake_grace_ms: int = 300      # 提示音播完后再留的余量（毫秒）


@dataclass
class PlayerConfig:
    mpv_binary: str = "mpv"
    mode: str = "order"
    volume: int = 80


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = ""


@dataclass
class Config:
    music: MusicConfig = field(default_factory=MusicConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    state: StateConfig = field(default_factory=StateConfig)
    player: PlayerConfig = field(default_factory=PlayerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    _SECTIONS: ClassVar[Dict[str, str]] = {
        "music": "music",
        "audio": "audio",
        "asr": "asr",
        "tts": "tts",
        "vad": "vad",
        "state": "state",
        "player": "player",
        "logging": "logging",
    }

    @classmethod
    def load(cls, path: str = None) -> "Config":
        cfg = cls()
        # 默认配置文件位于 config/config.yaml（与 commands.yaml 同目录）
        path = path or os.path.join(PROJECT_ROOT, "config", "config.yaml")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cfg._apply(data)
        # 相对路径按项目根目录解析（支持 "music"、"./music" 这类写法）
        if not os.path.isabs(cfg.music.dir):
            cfg.music.dir = os.path.join(PROJECT_ROOT, cfg.music.dir)
        # 环境变量覆盖音乐目录（开发机方便测试）
        env_dir = os.environ.get("VMP_MUSIC_DIR")
        if env_dir:
            cfg.music.dir = (
                env_dir if os.path.isabs(env_dir) else os.path.join(PROJECT_ROOT, env_dir)
            )
        return cfg

    def _apply(self, data: Dict) -> None:
        for key, attr in self._SECTIONS.items():
            section = data.get(key)
            if not section:
                continue
            obj = getattr(self, attr)
            for k, v in section.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

    def resolve_model_dir(self, rel: str) -> str:
        """把相对路径解析到项目根目录下。"""
        if os.path.isabs(rel):
            return rel
        return os.path.join(PROJECT_ROOT, rel)
