import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.music.player import NullPlayer, PlaybackController, PlayerMode
from app.music.state_store import PlaybackStateStore


class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "playback.json")
        self.store = PlaybackStateStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_tracks(self):
        d = os.path.join(self.tmp.name, "m")
        os.makedirs(d, exist_ok=True)
        paths = []
        for i in range(3):
            p = os.path.join(d, f"t{i}.wav")
            with open(p, "wb") as f:
                f.write(b"x")
            paths.append(p)
        return paths

    def test_save_load(self):
        tracks = self._make_tracks()
        self.store.save(tracks, 1, "order", volume=60, playlist_name="跑步")
        data = self.store.load()
        self.assertEqual(data["queue"], tracks)
        self.assertEqual(data["index"], 1)
        self.assertEqual(data["mode"], "order")
        self.assertEqual(data["volume"], 60)
        self.assertEqual(data["playlist_name"], "跑步")

    def test_load_missing_files_dropped(self):
        self.store.save(["/no/such/file.wav", "/also/missing.wav"], 0, "order")
        data = self.store.load()
        self.assertEqual(data["queue"], [])
        self.assertEqual(data["index"], 0)

    def test_controller_restore(self):
        tracks = self._make_tracks()
        self.store.save(tracks, 2, "order", volume=70, playlist_name="跑步")
        player = NullPlayer()
        ctrl = PlaybackController(player)
        state = self.store.load()
        self.assertTrue(ctrl.restore(state, autoplay=True))
        self.assertEqual(ctrl.get_current(), tracks[2])
        self.assertEqual(player.current, tracks[2])
        self.assertEqual(ctrl.mode, PlayerMode.ORDER)
        self.assertEqual(ctrl.playlist_name, "跑步")

    def test_restore_missing_queue_fails(self):
        player = NullPlayer()
        ctrl = PlaybackController(player)
        self.assertFalse(ctrl.restore({"queue": ["/no/file.wav"], "index": 0}))


if __name__ == "__main__":
    unittest.main()
