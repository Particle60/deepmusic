import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.commands.handler import CommandHandler
from app.commands.parser import parse_command
from app.music.library import MusicLibrary
from app.music.player import NullPlayer, PlaybackController
from app.music.playlists import PlaylistManager


class TestHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.music_dir = self.tmp.name
        for name in ["青花瓷.mp3", "晴天.mp3", "稻香.mp3"]:
            with open(os.path.join(self.music_dir, name), "wb") as f:
                f.write(b"x")
        self.library = MusicLibrary(self.music_dir)
        self.library.scan()
        self.playlists = PlaylistManager(self.music_dir, os.path.join(self.music_dir, "playlists"))
        self.player = NullPlayer()
        self.controller = PlaybackController(self.player)
        self.responses = []
        self.handler = CommandHandler(
            self.library, self.playlists, self.controller, respond=self.responses.append
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_play_song(self):
        self.handler.handle(parse_command("播放歌曲 青花瓷"))
        self.assertEqual(self.player.current, os.path.join(self.music_dir, "青花瓷.mp3"))

    def test_play_playlist_all(self):
        self.handler.handle(parse_command("播放歌单 all"))
        self.assertEqual(len(self.controller.queue), 3)

    def test_not_found(self):
        self.handler.handle(parse_command("播放歌曲 不存在的歌"))
        self.assertTrue(self.responses)
        self.assertIn("歌曲不存在", self.responses[0])

    def _write_pl(self, name, songs):
        pl_dir = os.path.join(self.music_dir, "playlists")
        os.makedirs(pl_dir, exist_ok=True)
        with open(os.path.join(pl_dir, f"{name}.m3u"), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n" + "\n".join(songs) + "\n")

    def test_play_song_switches_playlist(self):
        # 歌单"跑步"含晴天、稻香；歌单"安静"含青花瓷
        self._write_pl("跑步", ["晴天.mp3", "稻香.mp3"])
        self._write_pl("安静", ["青花瓷.mp3"])
        self.playlists.load_all()
        # 当前在"跑步"歌单
        self.controller.load(
            self.playlists.get("跑步").tracks, autoplay=True, playlist_name="跑步"
        )
        # 播放"青花瓷"（不在跑步歌单，在"安静"歌单）
        self.handler.handle(parse_command("播放歌曲 青花瓷"))
        self.assertEqual(
            self.controller.playlist_name, "安静"
        )  # 切到安静歌单
        self.assertEqual(self.player.current, os.path.join(self.music_dir, "青花瓷.mp3"))
        self.assertEqual(self.controller.queue, self.playlists.get("安静").tracks)

    def test_play_song_stays_in_current_playlist(self):
        self._write_pl("跑步", ["晴天.mp3", "稻香.mp3"])
        self.playlists.load_all()
        self.controller.load(
            self.playlists.get("跑步").tracks, autoplay=True, playlist_name="跑步"
        )
        self.handler.handle(parse_command("播放歌曲 稻香"))
        self.assertEqual(self.controller.playlist_name, "跑步")  # 保持当前歌单
        self.assertEqual(self.player.current, os.path.join(self.music_dir, "稻香.mp3"))
        self.assertEqual(self.controller.index, 1)  # 定位到稻香

    def test_play_song_falls_back_to_all(self):
        # 没有任何歌单含"晴天" → 落到默认歌单"所有歌曲"
        self._write_pl("跑步", ["稻香.mp3"])
        self.playlists.load_all()
        self.controller.load(
            self.playlists.get("跑步").tracks, autoplay=True, playlist_name="跑步"
        )
        self.handler.handle(parse_command("播放歌曲 晴天"))
        self.assertEqual(self.controller.playlist_name, "所有歌曲")
        self.assertEqual(self.player.current, os.path.join(self.music_dir, "晴天.mp3"))

    def test_volume(self):
        self.handler.handle(parse_command("音量调到 30"))
        self.assertEqual(self.player.get_volume(), 40)  # 下限 40
        self.handler.handle(parse_command("音量调到 60"))
        self.assertEqual(self.player.get_volume(), 60)
        self.handler.handle(parse_command("音量调到 300"))
        self.assertEqual(self.player.get_volume(), 100)  # 上限 100

    def test_mode(self):
        self.handler.handle(parse_command("随机播放"))
        self.assertEqual(self.controller.mode.name, "SHUFFLE")

    def test_pause_suppresses_resume(self):
        # 暂停后不应被自动恢复（暂停指令保持暂停）
        self.controller.load(self.library.all_playlist, autoplay=True)
        self.handler.handle(parse_command("暂停"))
        self.assertFalse(self.handler.should_resume_after())
        self.assertTrue(self.player.paused)

    def test_stop_suppresses_resume(self):
        # 停止后不应被自动恢复
        self.controller.load(self.library.all_playlist, autoplay=True)
        self.handler.handle(parse_command("停止"))
        self.assertFalse(self.handler.should_resume_after())
        self.assertEqual(self.controller.index, -1)

    def test_normal_command_allows_resume(self):
        # 普通指令（如切歌）后允许恢复音乐
        self.controller.load(self.library.all_playlist, autoplay=True)
        self.handler.handle(parse_command("下一首"))
        self.assertTrue(self.handler.should_resume_after())

    def test_resume_after_stop_restarts_queue(self):
        # 停止后说"继续"应从头重播当前队列
        self.controller.load(self.library.all_playlist, autoplay=True)
        self.handler.handle(parse_command("停止"))
        self.assertEqual(self.controller.index, -1)
        self.handler.handle(parse_command("继续"))
        self.assertEqual(self.controller.index, 0)  # 从头开始
        self.assertTrue(self.player.is_playing())

    def test_pause_then_wake_keeps_paused(self):
        # 暂停后误唤醒：pause_music 不应再标记"需要恢复"（保持暂停）
        self.controller.load(self.library.all_playlist, autoplay=True)
        self.handler.handle(parse_command("暂停"))
        self.assertTrue(self.player.is_paused())
        # 误唤醒：pause_music 应返回 False（已暂停，不标记恢复）
        self.assertFalse(self.handler.pause_music())
        self.assertTrue(self.player.is_paused())  # 保持暂停

    def _write_pl(self, name, songs):
        pl_dir = os.path.join(self.music_dir, "playlists")
        os.makedirs(pl_dir, exist_ok=True)
        with open(os.path.join(pl_dir, f"{name}.m3u"), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n" + "\n".join(songs) + "\n")

    def test_refresh_updates_current_playlist_queue(self):
        # 更新歌单后，当前正在播放的具名歌单队列应同步刷新（保持当前曲目）
        self._write_pl("跑步", ["青花瓷.mp3", "晴天.mp3"])
        self.playlists.load_all()
        self.controller.load(
            self.playlists.get("跑步").tracks, autoplay=True, playlist_name="跑步"
        )
        # 往 跑步.m3u 加一首稻香
        self._write_pl("跑步", ["青花瓷.mp3", "晴天.mp3", "稻香.mp3"])
        self.playlists.load_all()
        self.handler.handle(parse_command("更新歌单"))
        # 当前队列应包含新增歌曲，且当前曲目保持
        self.assertEqual(len(self.controller.queue), 3)
        self.assertEqual(
            self.controller.get_current(),
            os.path.join(self.music_dir, "青花瓷.mp3"),
        )


if __name__ == "__main__":
    unittest.main()
