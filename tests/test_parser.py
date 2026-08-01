import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.commands.parser import parse_command


class TestParser(unittest.TestCase):
    def test_play_song_bracketed(self):
        cmd = parse_command("播放歌曲《青花瓷》")
        self.assertEqual(cmd.intent, "play_song")
        self.assertEqual(cmd.args["name"], "青花瓷")

    def test_play_song_plain(self):
        cmd = parse_command("播放歌曲 青花瓷")
        self.assertEqual(cmd.intent, "play_song")
        self.assertEqual(cmd.args["name"], "青花瓷")

    def test_play_song_requires_prefix(self):
        # 不带"歌曲"前缀的播放命令不再匹配歌曲
        self.assertEqual(parse_command("播放 青花瓷").intent, "unknown")
        self.assertEqual(parse_command("播放《青花瓷》").intent, "unknown")

    def test_play_playlist(self):
        cmd = parse_command("播放歌单《跑步》")
        self.assertEqual(cmd.intent, "play_playlist")
        self.assertEqual(cmd.args["name"], "跑步")

    def test_play_playlist_plain(self):
        cmd = parse_command("播放歌单 跑步")
        self.assertEqual(cmd.intent, "play_playlist")
        self.assertEqual(cmd.args["name"], "跑步")

    def test_play_all_songs(self):
        cmd = parse_command("播放所有歌曲")
        self.assertEqual(cmd.intent, "play_playlist")
        self.assertEqual(cmd.args["name"], "所有歌曲")

    def test_play_index(self):
        cmd = parse_command("播放第3首")
        self.assertEqual(cmd.intent, "play_index")
        self.assertEqual(cmd.args["index"], 2)

    def test_next_prev(self):
        self.assertEqual(parse_command("下一首").intent, "next")
        self.assertEqual(parse_command("上一首").intent, "prev")
        self.assertEqual(parse_command("下一首歌").intent, "next")
        self.assertEqual(parse_command("播放下一首").intent, "next")
        self.assertEqual(parse_command("播放下一首歌").intent, "next")
        self.assertEqual(parse_command("上一首歌").intent, "prev")
        self.assertEqual(parse_command("播放上一首").intent, "prev")
        self.assertEqual(parse_command("播放上一首歌").intent, "prev")
        self.assertEqual(parse_command("回到上一首歌").intent, "prev")

    def test_control(self):
        self.assertEqual(parse_command("暂停").intent, "pause")
        self.assertEqual(parse_command("继续").intent, "resume")
        self.assertEqual(parse_command("播放").intent, "resume")
        self.assertEqual(parse_command("停止").intent, "stop")
        self.assertEqual(parse_command("随机播放").intent, "mode")
        self.assertEqual(parse_command("顺序播放").intent, "mode")
        self.assertEqual(parse_command("单曲循环").intent, "mode")
        self.assertEqual(parse_command("列表循环").intent, "mode")

    def test_mode_args(self):
        self.assertEqual(parse_command("随机播放").args["mode"], "shuffle")
        self.assertEqual(parse_command("顺序播放").args["mode"], "order")
        self.assertEqual(parse_command("单曲循环").args["mode"], "repeat_one")
        self.assertEqual(parse_command("列表循环").args["mode"], "repeat_all")

    def test_volume(self):
        cmd = parse_command("音量调到 60")
        self.assertEqual(cmd.intent, "set_volume")
        self.assertEqual(cmd.args["volume"], 60)
        self.assertEqual(parse_command("音量加大").intent, "volume_up")
        self.assertEqual(parse_command("音量减小").intent, "volume_down")
        self.assertEqual(parse_command("把音量调大点").intent, "volume_up")
        self.assertEqual(parse_command("音量增大").intent, "volume_up")
        self.assertEqual(parse_command("增大音量").intent, "volume_up")
        self.assertEqual(parse_command("把音量调小点").intent, "volume_down")
        self.assertEqual(parse_command("减小音量").intent, "volume_down")

    def test_status(self):
        self.assertEqual(parse_command("现在放的是什么歌").intent, "status")

    def test_current_playlist(self):
        self.assertEqual(parse_command("现在歌单是什么").intent, "current_playlist")
        self.assertEqual(parse_command("现在歌单是啥").intent, "current_playlist")
        # 只识别"现在歌单"，"当前歌单"不再识别
        self.assertEqual(parse_command("当前歌单是什么").intent, "unknown")
        self.assertEqual(parse_command("当前歌单是哪个").intent, "unknown")

    def test_list_playlists(self):
        self.assertEqual(parse_command("列出歌单").intent, "list_playlists")
        self.assertEqual(parse_command("列出所有歌单").intent, "list_playlists")
        self.assertEqual(parse_command("查看歌单").intent, "list_playlists")
        self.assertEqual(parse_command("有哪些歌单").intent, "list_playlists")

    def test_unknown(self):
        self.assertEqual(parse_command("今天天气不错").intent, "unknown")
        self.assertEqual(parse_command("").intent, "unknown")

    def test_prefix_noise_cleaned(self):
        # ASR 常见前缀噪声应被清理后再解析
        self.assertEqual(parse_command("a 你播放歌曲青花瓷").intent, "play_song")
        self.assertEqual(parse_command("嗯 播放歌曲青花瓷").args["name"], "青花瓷")
        self.assertEqual(parse_command("那个 下一首").intent, "next")
        self.assertEqual(parse_command("好的 播放歌单 跑步").intent, "play_playlist")

    def test_asr_noise_tolerant(self):
        # 实测 ASR 常见噪声：叠字/丢字/同音字，模糊兜底应能命中
        self.assertEqual(parse_command("随机播").intent, "mode")
        self.assertEqual(parse_command("随随机播").intent, "mode")
        self.assertEqual(parse_command("谁机播放").intent, "mode")
        self.assertEqual(parse_command("单曲播").intent, "mode")
        self.assertEqual(parse_command("顺顺序播").intent, "mode")
        self.assertEqual(parse_command("把声音调小点").intent, "volume_down")
        self.assertEqual(parse_command("把声音调大点").intent, "volume_up")
        self.assertEqual(parse_command("现在各单是什么").intent, "current_playlist")
        self.assertEqual(parse_command("现在播放的是什么").intent, "status")

    def test_fuzzy_does_not_overmatch(self):
        # 模糊匹配不能把差异大的近义文本误判（用户明确要求"当前歌单"不识别）
        self.assertEqual(parse_command("当前歌单是什么").intent, "unknown")
        self.assertEqual(parse_command("当前歌单是哪个").intent, "unknown")
        self.assertEqual(parse_command("今天天气不错").intent, "unknown")

    def test_set_volume_chinese_and_arabic(self):
        # 把音量/把声音 调到 N（支持中文数字与阿拉伯数字）
        cases = {
            "把音量调到六十": 60,
            "把声音调到60": 60,
            "把音量调到 60": 60,
            "把声音调到六十": 60,
            "声音调到 60": 60,
            "音量调到 60": 60,
            "把声音调到一百": 100,
            "把音量调到二十一": 21,
            "把声音调到五": 5,
            "音量调到 8": 8,
        }
        for text, vol in cases.items():
            with self.subTest(text=text):
                cmd = parse_command(text)
                self.assertEqual(cmd.intent, "set_volume")
                self.assertEqual(cmd.args.get("volume"), vol)

    def test_cn_to_int(self):
        from app.commands.parser import cn_to_int

        self.assertEqual(cn_to_int("六十"), 60)
        self.assertEqual(cn_to_int("一百"), 100)
        self.assertEqual(cn_to_int("二十一"), 21)
        self.assertEqual(cn_to_int("十"), 10)
        self.assertEqual(cn_to_int("8"), 8)
        self.assertEqual(cn_to_int("五"), 5)

    def test_int_to_cn(self):
        from app.commands.parser import cn_to_int, int_to_cn

        self.assertEqual(int_to_cn(0), "零")
        self.assertEqual(int_to_cn(6), "六")
        self.assertEqual(int_to_cn(60), "六十")
        self.assertEqual(int_to_cn(100), "一百")
        self.assertEqual(int_to_cn(21), "二十一")
        self.assertEqual(int_to_cn(15), "十五")
        self.assertEqual(int_to_cn(88), "八十八")
        # 往返：中文数字 → int → 中文读法
        self.assertEqual(int_to_cn(cn_to_int("六十")), "六十")


if __name__ == "__main__":
    unittest.main()
