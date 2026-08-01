import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audio.fake_mic import FakeMicReader


def _make_wav(path, frames, sample_rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)


class TestFakeMic(unittest.TestCase):
    def test_read_wav_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wav")
            frames = b"\x01\x00" * 1600  # 1600 帧 = 3200 字节 = 100ms @16k
            _make_wav(path, frames)
            mic = FakeMicReader(path, chunk_bytes=3200)
            mic.open()
            try:
                self.assertFalse(mic.eof)
                chunk = mic.read_chunk(3200)
                self.assertEqual(len(chunk), 3200)
                self.assertEqual(chunk, frames)
                # 再读一次到达文件尾，eof 置位
                mic.read_chunk(3200)
                self.assertTrue(mic.eof)
            finally:
                mic.close()

    def test_read_wav_loop(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wav")
            frames = b"\x01\x00" * 1600
            _make_wav(path, frames)
            mic = FakeMicReader(path, chunk_bytes=3200, loop=True)
            mic.open()
            try:
                c1 = mic.read_chunk(3200)
                c2 = mic.read_chunk(3200)
                self.assertEqual(c1, frames)
                self.assertEqual(c2, frames)  # 循环后仍返回同一段
            finally:
                mic.close()

    def test_short_wav_pads_with_silence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wav")
            _make_wav(path, b"\x01\x00" * 160)  # 只有 160 帧 = 320 字节
            mic = FakeMicReader(path, chunk_bytes=3200)
            mic.open()
            try:
                chunk = mic.read_chunk(3200)
                self.assertEqual(len(chunk), 3200)
                self.assertEqual(chunk[:320], b"\x01\x00" * 160)
                self.assertTrue(all(b == 0 for b in chunk[320:]))
                self.assertTrue(mic.eof)
            finally:
                mic.close()


if __name__ == "__main__":
    unittest.main()
