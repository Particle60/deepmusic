"""开发期控制台：无麦克风/扬声器，用文本注入模拟语音指令。"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.audio.speaker import Speaker  # noqa: E402
from app.commands.handler import CommandHandler  # noqa: E402
from app.config import Config  # noqa: E402
from app.music.library import MusicLibrary  # noqa: E402
from app.music.player import NullPlayer, PlaybackController  # noqa: E402
from app.music.playlists import PlaylistManager  # noqa: E402
from app.music.state_store import PlaybackStateStore  # noqa: E402
from app.state_machine import VoiceApp  # noqa: E402

HELP = """\
离线语音音乐播放器 · 开发控制台（无硬件模式）
直接输入模拟语音指令（回车执行），控制命令以 ! 开头：
  !help !scan !all !playlists !status !mode !vol
  !q / !quit / !exit  退出
语音指令示例：
  播放 青花瓷
  播放歌单 跑步
  创建歌单 跑步
  把 青花瓷 加入歌单 跑步
  随机播放 / 顺序播放 / 单曲循环 / 列表循环
  下一首 / 上一首 / 暂停 / 继续 / 停止
  音量调到 60 / 音量加大 / 音量减小
  现在放的是什么歌
"""


def build_app(cfg: Config, real_player: bool = False) -> VoiceApp:
    """搭建完整应用（音乐库 + 歌单 + 播放器 + 指令处理）。"""
    library = MusicLibrary(cfg.music.dir, cfg.music.extensions)
    library.scan()
    playlists = PlaylistManager(cfg.music.dir, cfg.music.resolved_playlists_dir)
    if real_player:
        from app.music.player import MpvPlayer

        player = MpvPlayer(
            mpv_binary=cfg.player.mpv_binary,
            ao=cfg.audio.ao,
            volume=cfg.player.volume,
        )
        player.open()
    else:
        player = NullPlayer()
    controller = PlaybackController(player, mode=cfg.player.mode)
    # 歌曲播完自动按播放模式切下一首（顺序/随机/循环）
    if hasattr(player, "on_track_end"):
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
        print(f"  [播报] {msg}")
        speaker.say(msg)

    handler = CommandHandler(library, playlists, controller, respond=respond,
                             state_store=state_store)
    app = VoiceApp(mic=None, vad=None, wake=None, asr=None, handler=handler, speaker=speaker)
    # 供控制台 ! 命令访问
    app.library = library
    app.playlists = playlists
    app.controller = controller
    app.state_store = state_store
    return app


def main(cfg: Config = None) -> int:
    cfg = cfg or Config.load()
    real_player = os.environ.get("VMP_REAL_PLAYER", "") == "1"
    app = build_app(cfg, real_player=real_player)
    if real_player:
        app.handler.restore()  # 恢复上次播放状态（断电/重启）
    print(HELP)
    try:
        while True:
            try:
                line = input("语音> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.startswith("!"):
                if line in ("!quit", "!q", "!exit"):
                    break
                _handle_bang(app, line)
                continue
            app.inject_text(line)
    finally:
        if real_player:
            app.handler.save_state()  # 退出前保存当前播放状态
            app.controller.player.close()
        app.speaker.close()
    print("bye")
    return 0


def _handle_bang(app: VoiceApp, line: str) -> None:
    if line == "!help":
        print(HELP)
    elif line == "!scan":
        n = len(app.library.scan())
        print(f"  扫描完成，共 {n} 首")
    elif line == "!all":
        pl = app.library.all_playlist
        print(f"  all 共 {len(pl)} 首")
        for i, p in enumerate(pl[:20], 1):
            print(f"    {i}. {os.path.basename(p)}")
        if len(pl) > 20:
            print(f"    ... 共 {len(pl)} 首")
    elif line == "!playlists":
        print("  歌单：", "、".join(app.playlists.list_names()) or "无")
    elif line == "!status":
        cur = app.controller.get_current()
        print(f"  当前播放：{os.path.basename(cur) if cur else '无'}  模式={app.controller.mode.label}")
    elif line == "!mode":
        print(f"  当前模式：{app.controller.mode.label}")
    elif line == "!vol":
        print(f"  当前音量：{app.controller.player.get_volume()}")
    else:
        print("  未知控制命令，输入 !help 查看")


if __name__ == "__main__":
    sys.exit(main())
