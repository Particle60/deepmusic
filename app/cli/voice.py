"""语音模式：真实麦克风 + 唤醒 + 识别 全链路（Phase 2/3 使用，需硬件/模型）。"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.asr.engine import AsrEngine  # noqa: E402
from app.asr.vad import EnergyVad  # noqa: E402
from app.asr.wake import WakeWordDetector  # noqa: E402
from app.audio.mic import create_mic  # noqa: E402
from app.audio.speaker import Speaker  # noqa: E402
from app.commands.handler import CommandHandler  # noqa: E402
from app.config import Config  # noqa: E402
from app.music.library import MusicLibrary  # noqa: E402
from app.music.player import MpvPlayer, PlaybackController  # noqa: E402
from app.music.playlists import PlaylistManager  # noqa: E402
from app.music.state_store import PlaybackStateStore  # noqa: E402
from app.state_machine import VoiceApp  # noqa: E402


def main(cfg: Config = None) -> int:
    cfg = cfg or Config.load()
    library = MusicLibrary(cfg.music.dir, cfg.music.extensions)
    library.scan()
    playlists = PlaylistManager(cfg.music.dir, cfg.music.resolved_playlists_dir)
    player = MpvPlayer(
        mpv_binary=cfg.player.mpv_binary,
        ao=cfg.audio.ao,
        volume=cfg.player.volume,
    )
    controller = PlaybackController(player, mode=cfg.player.mode)
    # 歌曲播完自动按播放模式切下一首（顺序/随机/循环）
    player.on_track_end = controller.on_track_end
    speaker = Speaker(
        tts_enabled=cfg.tts.enabled,
        tts_model_dir=cfg.resolve_model_dir(cfg.tts.model_dir),
        tts_speaker_id=cfg.tts.speaker_id,
        tts_length_scale=cfg.tts.length_scale,
        volume=cfg.tts.volume,
        mpv_binary=cfg.player.mpv_binary,
    )
    state_store = PlaybackStateStore(cfg.resolve_model_dir("state/playback.json"))

    def respond(msg: str) -> None:
        print(f"[播报] {msg}")
        speaker.say(msg)

    handler = CommandHandler(library, playlists, controller, respond=respond,
                             state_store=state_store, speaker=speaker)

    asr = AsrEngine(cfg.resolve_model_dir(cfg.asr.model_dir),
                    sample_rate=cfg.audio.sample_rate)
    wake = WakeWordDetector(cfg.resolve_model_dir(cfg.asr.kws_model_dir),
                            sample_rate=cfg.audio.sample_rate,
                            keywords_file=cfg.asr.keywords_file or None)
    if not asr.load():
        print("ASR 模型加载失败，语音模式不可用")
        return 1
    if not wake.load():
        print("KWS 模型加载失败，语音模式不可用")
        return 1

    mic = create_mic(cfg.audio.mic_device, backend=cfg.audio.mic_backend,
                     sample_rate=cfg.audio.sample_rate)
    vad = EnergyVad(
        threshold=cfg.vad.energy_threshold,
        sample_rate=cfg.audio.sample_rate,
        silence_timeout_ms=cfg.vad.silence_timeout_ms,
    )
    app = VoiceApp(
        mic, vad, wake, asr, handler,
        speaker=speaker,
        wake_timeout_ms=cfg.state.wake_timeout_ms,
        wake_feedback_ms=cfg.state.wake_feedback_ms,
        post_wake_grace_ms=cfg.state.post_wake_grace_ms,
    )
    player.open()
    try:
        handler.restore()  # 恢复上次播放状态（断电/重启）
        speaker.say("开机成功")  # 启动完成提示音
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        handler.save_state()  # 退出前保存当前播放状态
        app.stop()
        player.close()
        speaker.close()  # 关闭常驻 mpv（提示音播放器）
    return 0


if __name__ == "__main__":
    sys.exit(main())
