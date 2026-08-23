"""扬声器/提示音输出封装 + 语音合成反馈（TTS）。

后端（可配置/自动检测）：
- sherpa-onnx：离线中文 TTS（上板正式，音质好）
- say：        macOS 系统语音（开发机）
- espeak-ng：  Linux 板兜底
- log：        无 TTS 工具时仅记录

提示音预合成缓存：唤醒/反馈等常用短语在初始化时一次性合成，
运行时直接播放缓存，避免即时合成造成的延迟。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Dict

log = logging.getLogger(__name__)

# 预合成缓存目录（磁盘缓存，重启后复用，省去重复合成）
_CACHE_DIR = "/tmp/vmp_tts_cache"
# 仓库内预生成音频目录（随项目一起拷贝到板子，启动即用、无需现场合成）
_REPO_CACHE_DIR = "assets/tts_cache"

# 需要预合成（提前生成）的固定提示短语
_PRECOMPILED_PHRASES = (
    "开机成功",
    "你好",
    "听不懂",
    "歌曲不存在",
    "已切换为随机播放",
    "已切换为顺序播放",
    "已切换为单曲循环",
    "已切换为列表循环",
    "继续播放",
    "已暂停",
    "已停止",
    "正在播放",
    "当前歌单",
    "所有歌曲",
    "当前没有在播放",
    "当前没有可用的播放列表",
    "歌单",
    "不存在",
)


class Speaker:
    """负责提示音与语音反馈。"""

    def __init__(self, tts_enabled: bool = False, tts_model_dir: str = "",
                 tts_speaker_id: int = 0, tts_length_scale: float = 1.0,
                 volume: int = 100, voice: str = "Tingting", mpv_binary: str = "mpv",
                 ao: str = ""):
        self.voice = voice
        self.tts_enabled = tts_enabled
        self.tts_model_dir = tts_model_dir
        self.tts_speaker_id = tts_speaker_id
        self.tts_length_scale = tts_length_scale
        self.volume = max(0, min(100, int(volume)))
        self.mpv_binary = mpv_binary
        self.ao = ao  # 提示音 mpv 的输出，应与音乐播放共用同一设备
        self._backend = self._detect_backend()
        self._tts = None
        self._cache: Dict[str, str] = {}  # 短语 -> wav 文件路径
        self._player = None  # 常驻 mpv（提示音播放），避免每次冷启动延迟
        if tts_enabled:
            self._load_offline_tts()
        self._ensure_player()

    @staticmethod
    def _detect_backend() -> str:
        if sys.platform == "darwin" and shutil.which("say"):
            return "say"
        if shutil.which("espeak-ng"):
            return "espeak-ng"
        if shutil.which("espeak"):
            return "espeak"
        return "log"  # 无 TTS 工具时仅记录

    def _load_offline_tts(self) -> None:
        """加载 sherpa-onnx 离线中文 TTS 模型，并预合成常用提示短语。"""
        try:
            import sherpa_onnx  # type: ignore

            tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=self.tts_model_dir + "/model.onnx",
                        lexicon=self.tts_model_dir + "/lexicon.txt",
                        tokens=self.tts_model_dir + "/tokens.txt",
                        length_scale=self.tts_length_scale,
                    ),
                    num_threads=2,
                ),
            ))
            self._tts = tts
            self._backend = "sherpa-onnx"
            log.info("离线 TTS 已加载：%s (speaker %d)", self.tts_model_dir, self.tts_speaker_id)
            self._precompile()
        except Exception:  # noqa: BLE001
            log.warning("离线 TTS 加载失败，回退到 %s", self._backend, exc_info=True)
            self._tts = None

    # ---- 预合成缓存 ----
    def _repo_cache_dir(self) -> str:
        """仓库内预生成音频目录的绝对路径（相对项目根）。"""
        import os

        from ..config import PROJECT_ROOT

        return os.path.join(PROJECT_ROOT, _REPO_CACHE_DIR)

    def _precompile(self) -> None:
        """加载预生成提示短语音频：优先仓库 assets/tts_cache，缺失的现场合成。"""
        repo_dir = self._repo_cache_dir()
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
        except OSError:
            pass
        loaded = 0
        missing = []
        for text in _PRECOMPILED_PHRASES:
            key = self._cache_key(text)
            # 1) 仓库内预生成音频（随项目分发，最优）
            repo_path = os.path.join(repo_dir, f"{key}.wav")
            if os.path.exists(repo_path):
                self._cache[text] = repo_path
                loaded += 1
                continue
            # 2) 本地磁盘缓存
            path = os.path.join(_CACHE_DIR, f"{key}.wav")
            if os.path.exists(path):
                self._cache[text] = path
                loaded += 1
                continue
            missing.append(text)
        if loaded:
            log.info("加载预生成提示短语 %d 条（仓库 %s）", loaded, repo_dir)
        if missing:
            log.info("需现场合成 %d 条：%s", len(missing), missing)
            self._synthesize(missing, repo_dir)

    @staticmethod
    def _cache_key(text: str) -> str:
        # 用文本的简单哈希作为文件名（避免中文路径问题）
        import hashlib

        return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize(samples) -> "object":
        import numpy as np

        peak = float(np.abs(samples).max()) if samples.size else 0.0
        target = 0.9
        if peak > 0 and peak < 0.5:
            samples = samples * (target / peak)
        return np.clip(samples, -1.0, 1.0)

    def _synthesize(self, texts, repo_dir: str) -> None:
        """现场合成缺失的短语，保存到仓库目录 + 本地缓存。"""
        import numpy as np

        for text in texts:
            key = self._cache_key(text)
            audio = self._tts.generate(text, sid=self.tts_speaker_id)
            samples = np.asarray(audio.samples, dtype=np.float32)
            samples = self._normalize(samples)
            import wave

            # 存仓库目录（下次随项目分发）
            for d in (repo_dir, _CACHE_DIR):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    continue
                w = wave.open(os.path.join(d, f"{key}.wav"), "wb")
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self._tts.sample_rate)
                w.writeframes((samples * 32767).astype(np.int16).tobytes())
                w.close()
            self._cache[text] = os.path.join(repo_dir, f"{key}.wav")

    def say(self, text: str) -> None:
        """语音播报（TTS）。优先播放预合成缓存，未命中才即时合成。"""
        log.info("[speaker] say: %s (backend=%s)", text, self._backend)
        try:
            if self._tts is not None:
                # 精确命中缓存直接播放
                cached = self._cache.get(text)
                if cached and os.path.exists(cached):
                    self._play_wav(cached)
                    return
                # 尝试在预编译短语中找可拼接的固定片段（如 "歌单" + 名称 + "为空或不存在"）
                self._play_offline(text)
                return
            if self._backend == "log":
                return
            if self._backend == "say":
                subprocess.Popen(
                    ["say", "-v", self.voice, "-r", "190", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:  # espeak-ng / espeak
                subprocess.Popen(
                    [self._backend, "-v", "zh", "-a", str(self.volume), text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:  # noqa: BLE001
            log.warning("TTS 播放失败", exc_info=True)

    def say_duration(self, text: str) -> float:
        """返回指定文本播报音频的大致时长（秒）。用于精确计算提示音静默期。

        命中预合成缓存时读 wav 实际时长；否则按中文语速粗略估算（约 4.5 字/秒）。
        """
        cached = self._cache.get(text)
        if cached and os.path.exists(cached):
            try:
                import wave

                w = wave.open(cached, "rb")
                dur = w.getnframes() / w.getframerate()
                w.close()
                return dur
            except Exception:  # noqa: BLE001
                pass
        # 未缓存（动态内容）：粗略按语速估算
        chars = len([c for c in text if not c.isspace()])
        return max(0.3, chars / 4.5)

    def _play_wav(self, path: str) -> None:
        """用常驻 mpv 播放 wav（复用进程，避免每次冷启动 ~1s 延迟）。"""
        if self._player is not None and self._player.is_playing():
            try:
                self._player.play(path)
                return
            except Exception:  # noqa: BLE001
                log.warning("常驻 mpv 播放失败，回退到独立进程", exc_info=True)
        # 兜底：独立 mpv 进程（同样显式指定输出，避免板子自动检测无输出）
        cmd = [self.mpv_binary, "--no-video", "--really-quiet",
               f"--volume={self.volume}"]
        if self.ao:
            if "/" in self.ao:
                ao_name, _, ao_dev = self.ao.partition("/")
                cmd.append(f"--ao={ao_name}")
                cmd.append(f"--audio-device=alsa/{ao_dev}")
            else:
                cmd.append(f"--ao={self.ao}")
        cmd.append(path)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _ensure_player(self) -> None:
        """确保常驻 mpv 播放器存在（供提示音快速播放）。"""
        try:
            from ..music.player import MpvPlayer

            self._player = MpvPlayer(
                mpv_binary=self.mpv_binary,
                ao=self.ao,  # 与音乐播放共用同一输出（板子上须与 music 一致，如 alsa）
                volume=self.volume,
            )
            self._player.open()
        except Exception:  # noqa: BLE001
            log.warning("常驻 mpv 播放器初始化失败，提示音将使用独立进程", exc_info=True)
            self._player = None

    def close(self) -> None:
        """关闭常驻 mpv 播放器（退出时调用）。"""
        if self._player is not None:
            try:
                self._player.close()
            except Exception:  # noqa: BLE001
                pass
            self._player = None

    def _play_offline(self, text: str) -> None:
        """即时合成（动态内容如歌名/歌单名），交给 mpv 播放。"""
        import numpy as np

        audio = self._tts.generate(text, sid=self.tts_speaker_id)
        samples = np.asarray(audio.samples, dtype=np.float32)
        samples = self._normalize(samples)
        path = "/tmp/vmp_tts.wav"
        import wave

        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(self._tts.sample_rate)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())
        w.close()
        self._play_wav(path)
