"""播放列表（.m3u）管理：歌单以文件持久化，存相对音乐目录的路径。

歌单文件手动编辑，路径使用相对于音乐目录的相对路径（如 `晴天.wav`、
`金曲/mp3/陈奕迅-红玫瑰.mp3`），加载时自动解析为绝对路径供播放器使用。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Playlist:
    name: str
    tracks: List[str] = field(default_factory=list)  # 绝对路径


class PlaylistManager:
    """歌单以 .m3u 文件存储于 <music_dir>/playlists/，随扫描自动发现。"""

    def __init__(self, music_dir: str, playlists_dir: str):
        self.music_dir = music_dir
        self.playlists_dir = playlists_dir
        self.playlists: Dict[str, Playlist] = {}
        os.makedirs(self.playlists_dir, exist_ok=True)
        self.load_all()

    # ---- 文件 IO ----
    def _path_for(self, name: str) -> str:
        return os.path.join(self.playlists_dir, f"{name}.m3u")

    def _to_abs(self, p: str) -> str:
        """歌单里的相对路径 → 绝对路径（相对于音乐目录）。"""
        if os.path.isabs(p):
            return p
        return os.path.join(self.music_dir, p)

    @staticmethod
    def _parse_lines(path: str) -> List[str]:
        lines: List[str] = []
        if not os.path.exists(path):
            return lines
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lines.append(line)
        return lines

    # ---- 业务 ----
    def load_all(self) -> None:
        self.playlists.clear()
        if not os.path.isdir(self.playlists_dir):
            return
        for name in sorted(os.listdir(self.playlists_dir)):
            if name.lower().endswith(".m3u"):
                base = name[:-4]
                rel_tracks = self._parse_lines(os.path.join(self.playlists_dir, name))
                # 只保留存在的文件；相对路径解析为绝对路径
                tracks = [
                    self._to_abs(t)
                    for t in rel_tracks
                    if os.path.exists(self._to_abs(t))
                ]
                self.playlists[base] = Playlist(base, tracks)

    def list_names(self) -> List[str]:
        return sorted(self.playlists.keys())

    def get(self, name: str) -> Optional[Playlist]:
        return self.playlists.get(name)

    def find_playlist_containing(
        self, track_path: str, order: Optional[List[str]] = None
    ) -> Optional[str]:
        """在歌单中查找包含某歌曲的歌单名（按 order 顺序遍历，找不到返回 None）。"""
        names = order or list(self.playlists.keys())
        for name in names:
            pl = self.playlists.get(name)
            if pl and track_path in pl.tracks:
                return name
        return None

    def delete(self, name: str) -> bool:
        """删除歌单文件（手动配置场景下用）。"""
        if name not in self.playlists:
            return False
        del self.playlists[name]
        path = self._path_for(name)
        if os.path.exists(path):
            os.remove(path)
        return True
