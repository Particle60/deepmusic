"""指令处理器：把意图映射到音乐库 / 歌单 / 播放器。"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from ..music.library import MusicLibrary
from ..music.player import PlaybackController, PlayerMode
from ..music.playlists import PlaylistManager
from ..music.state_store import PlaybackStateStore
from .parser import Command, int_to_cn

log = logging.getLogger(__name__)


class CommandHandler:
    def __init__(
        self,
        library: MusicLibrary,
        playlists: PlaylistManager,
        controller: PlaybackController,
        respond: Optional[Callable[[str], None]] = None,
        match_threshold: float = 0.6,
        state_store: Optional[PlaybackStateStore] = None,
        speaker: Optional["Speaker"] = None,
    ):
        self.library = library
        self.playlists = playlists
        self.controller = controller
        self.respond = respond or (lambda msg: log.info("[respond] %s", msg))
        self.match_threshold = match_threshold
        self.state_store = state_store
        self.speaker = speaker  # 提示音（用于音量联动）
        # 本次指令执行后是否自动恢复唤醒前暂停的音乐。
        # 暂停/停止类指令应保持暂停/停止，不被自动恢复覆盖。
        self._suppress_resume = False

    def handle(self, cmd: Command) -> bool:
        """执行指令，返回是否成功（失败时已播报"听不懂/歌曲不存在"等）。"""
        self._suppress_resume = False  # 默认：指令后允许恢复音乐
        method = getattr(self, f"_on_{cmd.intent}", None)
        if method is None:
            self.respond("听不懂")
            return False
        try:
            ok = method(cmd.args)
            self._persist()
            return True if ok is not False else False
        except Exception:  # noqa: BLE001
            log.exception("处理指令失败: %s", cmd)
            self.respond("执行出错，请重试")
            return False

    def should_resume_after(self) -> bool:
        """指令执行后是否应恢复唤醒前暂停的音乐（暂停/停止指令除外）。"""
        return not self._suppress_resume

    def resume_previous(self) -> None:
        """指令未能识别时，恢复唤醒前暂停的音乐。"""
        try:
            self.controller.resume()
        except Exception:  # noqa: BLE001
            log.warning("恢复播放失败", exc_info=True)

    def pause_music(self) -> bool:
        """唤醒时暂停当前音乐（若正在播放），返回是否曾暂停。

        仅在"有活跃曲目且未暂停"时暂停并标记恢复；已暂停/已停止时不标记，
        避免唤醒后指令失败被错误恢复播放。
        """
        try:
            if self.controller.has_active_track() and not self.controller.player.is_paused():
                self.controller.pause()
                return True
        except Exception:  # noqa: BLE001
            log.warning("暂停音乐失败", exc_info=True)
        return False

    def _persist(self) -> None:
        """保存播放状态到磁盘（断电/重启恢复）。"""
        if self.state_store is None:
            return
        try:
            snap = self.controller.snapshot()
            if snap["queue"]:
                self.state_store.save(
                    snap["queue"], snap["index"], snap["mode"],
                    volume=self.controller.player.get_volume(),
                    playlist_name=snap.get("playlist_name", ""),
                )
            else:
                self.state_store.clear()
        except Exception:  # noqa: BLE001
            log.warning("播放状态保存失败", exc_info=True)

    def save_state(self) -> None:
        """退出前保存当前播放状态（Ctrl+C/正常退出时调用）。"""
        self._persist()

    def restore(self) -> None:
        """启动时恢复上次播放状态；无有效队列时切到默认歌单"所有歌曲"。"""
        if self.state_store is None:
            return
        state = self.state_store.load()
        restored = False
        if state.get("queue"):
            restored = self.controller.restore(state, autoplay=True)
        if restored:
            self.controller.player.set_volume(int(state.get("volume", 80)))
            log.info(
                "已恢复上次播放: %d 首, 当前第 %d 首, 歌单=%s",
                len(state["queue"]), state.get("index", 0) + 1,
                self.controller.playlist_name,
            )
        else:
            # 无有效队列 → 默认歌单"所有歌曲"（仅初始化队列，不自动播放）
            all_paths = self.library.all_playlist
            if all_paths:
                self.controller.load(
                    all_paths, start_index=0, autoplay=False, playlist_name="所有歌曲"
                )
                log.info("无上次播放状态，默认歌单：所有歌曲（%d 首）", len(all_paths))

    # ---- 播放 ----
    _DEFAULT_PL_NAMES = ("所有歌曲", "all", "全部", "所有")

    def _on_play_song(self, args: dict) -> bool:
        name = args.get("name", "")
        tracks = self.library.find_song(name, threshold=self.match_threshold, top_n=3)
        if not tracks:
            self.respond("歌曲不存在")
            return False
        path = tracks[0].path
        current_pl = self.controller.playlist_name

        # 情况1：当前在默认歌单"所有歌曲"（或无歌单）→ 直接在默认歌单里定位播放
        if current_pl in ("",) or current_pl in self._DEFAULT_PL_NAMES:
            all_paths = self.library.all_playlist
            idx = all_paths.index(path) if path in all_paths else 0
            self.controller.load(
                all_paths, start_index=idx, autoplay=True, playlist_name="所有歌曲"
            )
            return True

        # 情况2：歌曲就在当前歌单 → 当前歌单内定位播放
        current = self.playlists.get(current_pl)
        if current and path in current.tracks:
            self.controller.load(
                current.tracks,
                start_index=current.tracks.index(path),
                autoplay=True,
                playlist_name=current_pl,
            )
            return True

        # 情况3：遍历其他歌单（跳过当前歌单），找到则切到该歌单
        others = [
            n
            for n in self.playlists.list_names()
            if n != current_pl and n not in self._DEFAULT_PL_NAMES
        ]
        found = self.playlists.find_playlist_containing(path, order=others)
        if found:
            pl = self.playlists.get(found)
            self.controller.load(
                pl.tracks,
                start_index=pl.tracks.index(path),
                autoplay=True,
                playlist_name=found,
            )
            return True

        # 情况4：所有歌单都没有 → 切到默认歌单"所有歌曲"
        all_paths = self.library.all_playlist
        idx = all_paths.index(path) if path in all_paths else 0
        self.controller.load(
            all_paths, start_index=idx, autoplay=True, playlist_name="所有歌曲"
        )
        return True

    def _on_play_playlist(self, args: dict) -> bool:
        name = args.get("name", "")
        if name in ("所有歌曲", "all", "全部", "所有"):
            paths = self.library.all_playlist
            pl_name = "所有歌曲"
        else:
            pl = self.playlists.get(name)
            # 精确匹配失败 → 拼音模糊匹配兜底（ASR 识别不准，如"跑"→"跑步"）
            if pl is None:
                from ..music.pinyin_match import best_match

                matched = best_match(name, self.playlists.list_names(),
                                    threshold=0.5, top_n=1)
                if matched:
                    pl = self.playlists.get(matched[0][0])
                    log.info("歌单模糊匹配: %s → %s", name, matched[0][0])
            paths = pl.tracks if pl else []
            pl_name = pl.name if pl else name
        if not paths:
            self.respond(f"歌单《{pl_name}》不存在")
            return False
        # 成功播放：静默执行，不播报
        self.controller.load(paths, autoplay=True, playlist_name=pl_name)
        return True

    def _on_play_index(self, args: dict) -> bool:
        idx = int(args.get("index", 0))
        if not self.controller.play_index(idx):
            self.respond("当前没有可用的播放列表")
            return False
        return True

    def _on_list_playlists(self, args: dict) -> bool:
        names = self.playlists.list_names()
        self.respond("现在歌单：" + ("、".join(names) if names else "无"))
        return True

    def _on_refresh_playlists(self, args: dict) -> bool:
        """不重启程序：重新扫描音乐库 + 重载歌单文件（含新增/删除歌单）。"""
        try:
            self.library.scan()
            self.playlists.load_all()
            # 若正在播放某个具名歌单，同步刷新当前播放队列（保持当前曲目）
            pl_name = self.controller.playlist_name
            if pl_name and pl_name not in ("", "所有歌曲"):
                pl = self.playlists.get(pl_name)
                if pl:
                    self.controller.reload_queue(pl.tracks)
            # 内置默认歌单"所有歌曲" + 歌单目录里的歌单
            names = ["所有歌曲"] + self.playlists.list_names()
            self.respond(f"已更新歌单：{','.join(names)}")
            return True
        except Exception:  # noqa: BLE001
            log.exception("更新歌单失败")
            self.respond("更新歌单失败")
            return False

    def _on_current_playlist(self, args: dict) -> bool:
        """播报当前播放所在的歌单名。"""
        pl_name = self.controller.playlist_name or "所有歌曲"
        cur = self.controller.get_current()
        if cur:
            self.respond(f"现在歌单：{pl_name}")
        else:
            self.respond("现在没有在播放")
        return True

    def _on_mode_status(self, args: dict) -> bool:
        """播报现在播放模式（顺序/随机/单曲循环/列表循环）。"""
        self.respond(f"现在播放模式：{self.controller.mode.label}")
        return True

    # ---- 播放控制 ----
    def _on_pause(self, args: dict) -> bool:
        self._suppress_resume = True  # 暂停后不自动恢复，保持暂停
        self.controller.pause()
        self.respond("已暂停")
        return True

    def _on_resume(self, args: dict) -> bool:
        self.controller.resume()
        return True

    def _on_stop(self, args: dict) -> bool:
        self._suppress_resume = True  # 停止后不自动恢复，保持停止
        self.controller.stop()
        self.respond("已停止")
        return True

    def _on_next(self, args: dict) -> bool:
        self.controller.next()
        return True

    def _on_prev(self, args: dict) -> bool:
        self.controller.prev()
        return True

    def _on_mode(self, args: dict) -> bool:
        mode = PlayerMode(args.get("mode", "order"))
        self.controller.set_mode(mode)
        self.respond(f"已切换为{mode.label}")
        return True

    def _on_set_volume(self, args: dict) -> bool:
        vol = max(40, min(100, int(args.get("volume", 80))))
        self.controller.player.set_volume(vol)
        if self.speaker is not None:
            self.speaker.set_volume(vol)  # 提示音与主音量联动
        self.respond(f"音量{int_to_cn(vol)}")
        return True

    def _on_volume_up(self, args: dict) -> bool:
        vol = min(100, self.controller.player.get_volume() + 10)
        self.controller.player.set_volume(vol)
        if self.speaker is not None:
            self.speaker.set_volume(vol)
        self.respond(f"音量{int_to_cn(vol)}")
        return True

    def _on_volume_down(self, args: dict) -> bool:
        vol = max(40, self.controller.player.get_volume() - 10)
        self.controller.player.set_volume(vol)
        if self.speaker is not None:
            self.speaker.set_volume(vol)
        self.respond(f"音量{int_to_cn(vol)}")
        return True

    def _on_status(self, args: dict) -> bool:
        cur = self.controller.get_current()
        if cur:
            title = os.path.splitext(os.path.basename(cur))[0]
            self.respond(f"现在播放的歌是：{title}")
        else:
            self.respond("现在没有在播放")
        return True
