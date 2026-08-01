"""播放状态持久化：保存/恢复 当前播放列表、模式、曲目位置（断电/重启恢复）。"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional


class PlaybackStateStore:
    """把播放状态存到 JSON 文件，重启后恢复。"""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def save(
        self,
        queue: list,
        index: int,
        mode: str,
        volume: Optional[int] = None,
        playlist_name: str = "",
    ) -> None:
        data = {
            "queue": list(queue),
            "index": int(index),
            "mode": str(mode),
            "playlist_name": str(playlist_name),
        }
        if volume is not None:
            data["volume"] = int(volume)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def load(self) -> Dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 校验并剔除已不存在的文件
            queue = data.get("queue", [])
            data["queue"] = [p for p in queue if os.path.exists(p)]
            if data["queue"] and data.get("index", -1) >= len(data["queue"]):
                data["index"] = 0
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def clear(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)
