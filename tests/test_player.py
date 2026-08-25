import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.music.player import NullPlayer, PlaybackController, PlayerMode


class TestPlayback(unittest.TestCase):
    def setUp(self):
        self.player = NullPlayer()
        self.controller = PlaybackController(self.player, mode=PlayerMode.ORDER)
        self.tracks = ["/m/a.mp3", "/m/b.mp3", "/m/c.mp3"]

    def test_load_and_play(self):
        self.controller.load(self.tracks)
        self.assertEqual(self.player.current, "/m/a.mp3")
        self.assertEqual(self.controller.index, 0)

    def test_next_prev(self):
        self.controller.load(self.tracks)
        self.controller.next()
        self.assertEqual(self.player.current, "/m/b.mp3")
        self.controller.prev()
        self.assertEqual(self.player.current, "/m/a.mp3")

    def test_order_end_stops(self):
        self.controller.load(self.tracks)
        self.controller.next()
        self.controller.next()
        self.controller.on_track_end()  # 最后一首播完 → 顺序模式停止
        self.assertIsNone(self.player.current)

    def test_stop_not_followed_by_auto_next(self):
        # 停止后 mpv 的 idle 事件（on_track_end）不应误触发自动切歌
        self.controller.load(self.tracks)
        self.controller.stop()
        self.assertEqual(self.controller.index, -1)
        self.assertIsNone(self.controller.get_current())
        # 模拟 mpv 停止后进入 idle 触发回调
        self.controller.on_track_end()
        self.assertIsNone(self.controller.get_current())  # 不应又切到 t0
        self.assertEqual(self.controller.index, -1)

    def test_repeat_all_wraps(self):
        self.controller.set_mode(PlayerMode.REPEAT_ALL)
        self.controller.load(self.tracks)
        self.controller.next()
        self.controller.next()
        self.controller.on_track_end()
        self.assertEqual(self.player.current, "/m/a.mp3")  # 回到第一首

    def test_repeat_one(self):
        self.controller.set_mode(PlayerMode.REPEAT_ONE)
        self.controller.load(self.tracks)
        self.controller.on_track_end()
        self.assertEqual(self.player.current, "/m/a.mp3")

    def test_shuffle(self):
        rng = random.Random(42)
        ctrl = PlaybackController(self.player, mode=PlayerMode.SHUFFLE, rng=rng)
        ctrl.load(self.tracks)
        self.assertIn(self.player.current, self.tracks)
        self.assertEqual(len(set(ctrl.shuffle_order)), 3)  # 无重复

    def test_shuffle_loop_after_end(self):
        # 随机播放播完整个洗牌序后，重新洗牌继续（不停止）
        rng = random.Random(7)
        ctrl = PlaybackController(self.player, mode=PlayerMode.SHUFFLE, rng=rng)
        ctrl.load(self.tracks)
        first_order = list(ctrl.shuffle_order)
        # 一路播到洗牌序末尾
        for _ in range(len(self.tracks) - 1):
            ctrl.on_track_end()
        # 再播完最后一首 → 应重新洗牌并继续播放（不停止）
        ctrl.on_track_end()
        self.assertIsNotNone(self.player.current)  # 仍在播放
        self.assertIn(ctrl.index, range(3))
        # 新的洗牌序不同于上一轮（大概率，随机种子固定）
        self.assertEqual(len(set(ctrl.shuffle_order)), 3)

    def test_set_mode_keeps_current_track(self):
        # 切换播放模式不打断当前歌曲（不立即切歌）
        self.controller.load(self.tracks)  # 当前播 a.mp3
        self.controller.set_mode(PlayerMode.SHUFFLE)
        self.assertEqual(self.player.current, "/m/a.mp3")  # 仍播当前歌
        self.assertEqual(self.controller.index, 0)
        # 洗牌序以当前曲目为起点
        self.assertEqual(self.controller.shuffle_order[0], 0)

    def test_volume_clamp(self):
        self.player.set_volume(80)
        self.assertEqual(self.player.get_volume(), 80)
        self.player.set_volume(300)
        self.assertEqual(self.player.get_volume(), 100)  # 上限 100
        self.player.set_volume(-5)
        self.assertEqual(self.player.get_volume(), 40)  # 下限 40

    def test_pause_resume(self):
        self.controller.load(self.tracks)
        self.controller.pause()
        self.assertFalse(self.player.is_playing())
        self.controller.resume()
        self.assertTrue(self.player.is_playing())

    def test_play_index(self):
        self.controller.load(self.tracks)
        self.assertTrue(self.controller.play_index(2))
        self.assertEqual(self.player.current, "/m/c.mp3")


if __name__ == "__main__":
    unittest.main()
