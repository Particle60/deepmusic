import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.music.pinyin_match import (
    _HAS_PYPINYIN,
    best_match,
    levenshtein,
    similarity,
)


class TestLevenshtein(unittest.TestCase):
    def test_same(self):
        self.assertEqual(levenshtein("abc", "abc"), 0)

    def test_one_diff(self):
        self.assertEqual(levenshtein("abc", "abd"), 1)

    def test_empty(self):
        self.assertEqual(levenshtein("", "abc"), 3)


class TestSimilarity(unittest.TestCase):
    def test_identical(self):
        self.assertAlmostEqual(similarity("青花瓷", "青花瓷"), 1.0, places=2)


class TestBestMatch(unittest.TestCase):
    def setUp(self):
        self.candidates = ["青花瓷", "晴天", "稻香", "平凡之路"]

    def test_exact(self):
        res = best_match("青花瓷", self.candidates, threshold=0.6)
        self.assertEqual(res[0][0], "青花瓷")

    def test_substring(self):
        res = best_match("青花", self.candidates, threshold=0.6)
        self.assertEqual(res[0][0], "青花瓷")

    @unittest.skipUnless(_HAS_PYPINYIN, "需要 pypinyin")
    def test_homophone(self):
        # 同音不同字：拼音一致，应命中
        res = best_match("晴天", ["晴天", "清天"], threshold=0.5)
        self.assertEqual(res[0][0], "晴天")

    def test_substring_songname(self):
        # 歌手-歌名 格式：查询"红玫瑰"应命中"陈奕迅-红玫瑰"
        res = best_match("红玫瑰", ["陈奕迅-红玫瑰", "红日"], threshold=0.6)
        self.assertEqual(res[0][0], "陈奕迅-红玫瑰")


if __name__ == "__main__":
    unittest.main()
