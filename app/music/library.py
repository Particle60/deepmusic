"""音乐库：扫描 SD 卡音乐目录、建立索引、生成 all 播放列表。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from .pinyin_match import best_match, to_pinyin

AUDIO_EXTENSIONS = [".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac"]


@dataclass(frozen=True)
class Track:
    path: str
    title: str
    pinyin: str


class MusicLibrary:
    """扫描音乐目录，缓存曲目索引；`all` 播放列表 = 全部曲目。"""

    def __init__(
        self,
        music_dir: str,
        extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
    ):
        self.music_dir = music_dir
        self.extensions = [e.lower() for e in (extensions or AUDIO_EXTENSIONS)]
        # 默认排除歌单目录等非音乐子目录
        self.exclude_dirs = [d.lower() for d in (exclude_dirs or ["playlists"])]
        self.tracks: List[Track] = []

    def scan(self) -> List[Track]:
        """扫描音乐目录（含子目录），返回并缓存曲目列表。"""
        self.tracks = []
        if not os.path.isdir(self.music_dir):
            return self.tracks
        for root, dirs, files in os.walk(self.music_dir):
            dirs[:] = [d for d in dirs if d.lower() not in self.exclude_dirs]
            for name in sorted(files):
                ext = os.path.splitext(name)[1].lower()
                if ext not in self.extensions:
                    continue
                path = os.path.join(root, name)
                title = os.path.splitext(name)[0]
                self.tracks.append(Track(path=path, title=title, pinyin=to_pinyin(title)))
        return self.tracks

    @property
    def all_playlist(self) -> List[str]:
        """all 播放列表：全部曲目路径，按文件名排序。"""
        return [t.path for t in sorted(self.tracks, key=lambda t: t.title)]

    def find_song(
        self, query: str, threshold: float = 0.6, top_n: int = 3
    ) -> List[Track]:
        """按拼音模糊匹配歌名，返回按相似度降序的曲目。"""
        titles = [t.title for t in self.tracks]
        matched = best_match(query, titles, threshold=threshold, top_n=top_n)
        by_title = {t.title: t for t in self.tracks}
        return [by_title[title] for title, _ in matched]
