import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.music.playlists import PlaylistManager


class TestPlaylists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.music_dir = os.path.join(self.tmp.name, "music")
        self.pl_dir = os.path.join(self.music_dir, "playlists")
        os.makedirs(self.pl_dir, exist_ok=True)
        # 造几首歌
        self.song1 = os.path.join(self.music_dir, "晴天.wav")
        self.song2 = os.path.join(self.music_dir, "金曲", "mp3", "红玫瑰.mp3")
        os.makedirs(os.path.dirname(self.song2), exist_ok=True)
        for p in (self.song1, self.song2):
            with open(p, "wb") as f:
                f.write(b"x")
        self.pm = PlaylistManager(self.music_dir, self.pl_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_m3u(self, name, lines):
        with open(os.path.join(self.pl_dir, f"{name}.m3u"), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n" + "\n".join(lines) + "\n")

    def test_load_relative_paths(self):
        # 手动配置：相对路径
        self._write_m3u("跑步", ["晴天.wav", "金曲/mp3/红玫瑰.mp3"])
        pm = PlaylistManager(self.music_dir, self.pl_dir)
        self.assertIn("跑步", pm.list_names())
        self.assertEqual(pm.get("跑步").tracks, [self.song1, self.song2])

    def test_load_absolute_paths(self):
        # 兼容绝对路径
        self._write_m3u("跑步", [self.song1])
        pm = PlaylistManager(self.music_dir, self.pl_dir)
        self.assertEqual(pm.get("跑步").tracks, [self.song1])

    def test_missing_files_filtered(self):
        self._write_m3u("跑步", ["晴天.wav", "不存在的歌.mp3"])
        pm = PlaylistManager(self.music_dir, self.pl_dir)
        self.assertEqual(pm.get("跑步").tracks, [self.song1])

    def test_persistence(self):
        self._write_m3u("跑步", ["晴天.wav"])
        pm2 = PlaylistManager(self.music_dir, self.pl_dir)  # 重新加载
        self.assertEqual(pm2.get("跑步").tracks, [self.song1])

    def test_delete(self):
        self._write_m3u("temp", ["晴天.wav"])
        pm = PlaylistManager(self.music_dir, self.pl_dir)
        self.assertTrue(pm.delete("temp"))
        self.assertNotIn("temp", pm.list_names())


if __name__ == "__main__":
    unittest.main()
