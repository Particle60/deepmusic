import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.music.library import MusicLibrary


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.music_dir = self.tmp.name
        for name in ["a.mp3", "b.flac", "c.wav"]:
            with open(os.path.join(self.music_dir, name), "wb") as f:
                f.write(b"x")
        with open(os.path.join(self.music_dir, "note.txt"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(self.music_dir, "playlists"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_counts(self):
        lib = MusicLibrary(self.music_dir)
        tracks = lib.scan()
        self.assertEqual(len(tracks), 3)

    def test_all_playlist_sorted(self):
        lib = MusicLibrary(self.music_dir)
        lib.scan()
        pl = lib.all_playlist
        self.assertEqual(len(pl), 3)
        self.assertEqual(os.path.basename(pl[0]), "a.mp3")

    def test_find_song(self):
        lib = MusicLibrary(self.music_dir)
        lib.scan()
        res = lib.find_song("a")
        self.assertTrue(res)
        self.assertEqual(res[0].title, "a")

    def test_missing_dir(self):
        lib = MusicLibrary("/nonexistent/path")
        self.assertEqual(lib.scan(), [])

    def test_excludes_playlists_dir(self):
        # 歌单目录里的 m3u 不应被当成歌曲
        os.makedirs(os.path.join(self.music_dir, "playlists"), exist_ok=True)
        with open(os.path.join(self.music_dir, "playlists", "x.m3u"), "w") as f:
            f.write("#EXTM3U\n")
        lib = MusicLibrary(self.music_dir)
        lib.scan()
        self.assertEqual(len(lib.tracks), 3)


if __name__ == "__main__":
    unittest.main()
