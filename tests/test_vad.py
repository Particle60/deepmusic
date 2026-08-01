import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.asr.vad import EnergyVad


class TestVad(unittest.TestCase):
    def _chunk(self, amplitude=0.0, n=1600):
        """构造 100ms 的 16bit PCM 块（振幅为 amplitude 的正弦）。"""
        import math
        import struct

        frames = bytearray()
        for t in range(n):
            v = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * t / 16000))
            frames += struct.pack("<h", v)
        return bytes(frames)

    def test_silence_no_start(self):
        vad = EnergyVad(threshold=120)
        for _ in range(20):
            evt = vad.feed(self._chunk(0.0))
            self.assertNotEqual(evt, "speech_start")

    def test_loud_speech_start(self):
        vad = EnergyVad(threshold=120)
        # 连续喂高振幅块：最终应进入 speaking，且出现过 speech_start
        evts = [vad.feed(self._chunk(0.5)) for _ in range(10)]
        self.assertIn("speech_start", evts)
        self.assertTrue(vad.speaking)

    def test_silence_ends_utterance(self):
        vad = EnergyVad(threshold=120, silence_timeout_ms=300, sample_rate=16000)
        for _ in range(5):
            vad.feed(self._chunk(0.5))  # 说话
        self.assertTrue(vad.speaking)
        # 足够长的静音应最终触发 speech_end
        evts = [vad.feed(self._chunk(0.0)) for _ in range(20)]
        self.assertIn("speech_end", evts)
        self.assertFalse(vad.speaking)


if __name__ == "__main__":
    unittest.main()
