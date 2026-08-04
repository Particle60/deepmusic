"""播放引擎：mpv JSON IPC 封装 + 播放控制（队列/模式）。"""
from __future__ import annotations

import enum
import json
import os
import random
import socket
import subprocess
import threading
import time
from typing import Callable, List, Optional


class PlayerMode(str, enum.Enum):
    """播放模式。"""

    ORDER = "order"          # 顺序播放，播完停止
    REPEAT_ALL = "repeat_all"  # 列表循环
    REPEAT_ONE = "repeat_one"  # 单曲循环
    SHUFFLE = "shuffle"        # 随机播放

    @property
    def label(self) -> str:
        return {
            "order": "顺序播放",
            "repeat_all": "列表循环",
            "repeat_one": "单曲循环",
            "shuffle": "随机播放",
        }[self.value]


class BasePlayer:
    """播放器抽象：具体实现由 mpv / 假播放器提供。"""

    def open(self) -> None:
        raise NotImplementedError

    def play(self, path: str) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_volume(self, volume: int) -> None:
        raise NotImplementedError

    def get_volume(self) -> int:
        raise NotImplementedError

    def is_playing(self) -> bool:
        raise NotImplementedError

    def is_paused(self) -> bool:
        """是否处于暂停状态。"""
        return False

    def close(self) -> None:
        raise NotImplementedError


class NullPlayer(BasePlayer):
    """假播放器：不依赖任何硬件/程序，供单元测试与开发期使用。"""

    def __init__(self):
        self.current: Optional[str] = None
        self.paused = False
        self.volume = 80

    def open(self) -> None:
        pass

    def play(self, path: str) -> None:
        self.current = path
        self.paused = False

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def stop(self) -> None:
        self.current = None
        self.paused = False

    def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))

    def get_volume(self) -> int:
        return self.volume

    def is_playing(self) -> bool:
        return self.current is not None and not self.paused

    def is_paused(self) -> bool:
        return self.paused

    def close(self) -> None:
        pass


class MpvPlayer(BasePlayer):
    """通过 mpv 的 JSON IPC 控制真实播放。开发期用 `ao=null` 无硬件验证。"""

    def __init__(
        self,
        socket_path: str = "/tmp/vmp_mpv.sock",
        mpv_binary: str = "mpv",
        ao: str = "null",
        volume: int = 80,
        on_track_end: Optional[Callable[[], None]] = None,
        extra_args: Optional[List[str]] = None,
    ):
        self.socket_path = socket_path
        self.mpv_binary = mpv_binary
        self.ao = ao
        self.volume = volume
        self.on_track_end = on_track_end
        self.extra_args = extra_args or []
        self.proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._req_id = 0
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._stop_evt = threading.Event()
        self.paused = False  # 暂停状态跟踪（mpv pause 属性）

    def open(self) -> None:
        if self._running:
            return
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        cmd = [
            self.mpv_binary,
            "--idle=yes",
            f"--input-ipc-server={self.socket_path}",
            f"--volume={self.volume}",
            "--no-video",
            "--really-quiet",
        ]
        if self.ao:
            # 支持 "alsa/plughw:1,0" 这种"输出+设备"写法：
            #   --ao=alsa --audio-device=alsa/plughw:1,0
            if "/" in self.ao:
                ao_name, _, ao_dev = self.ao.partition("/")
                cmd.append(f"--ao={ao_name}")
                cmd.append(f"--audio-device=alsa/{ao_dev}")
            else:
                cmd.append(f"--ao={self.ao}")
        cmd += self.extra_args
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._running = True
        self._stop_evt.clear()
        for _ in range(100):  # 等待 IPC socket 就绪
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.05)
        self._connect()  # 先连接，再启动读取线程，避免竞态
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if self._sock:
            self._send("observe_property", [1, "eof-reached"])
            self._send("observe_property", [2, "idle-active"])

    def _connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)

    def _send(self, command: str, args: Optional[List] = None) -> None:
        if not self._sock:
            return
        self._req_id += 1
        msg = {"command": [command] + (args or []), "request_id": self._req_id}
        try:
            self._sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _read_loop(self) -> None:
        buf = b""
        while self._running and not self._stop_evt.is_set():
            try:
                data = self._sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                self._handle_event(msg)
        self._running = False

    def _handle_event(self, msg: dict) -> None:
        if msg.get("event") != "property-change":
            return
        name = msg.get("name")
        data = msg.get("data")
        if name == "eof-reached" and data is True and self.on_track_end:
            self.on_track_end()
        elif name == "idle-active" and data is True and self.on_track_end:
            # 播放结束进入空闲时也触发一次，保证顺序播完能正确停止
            self.on_track_end()

    def play(self, path: str) -> None:
        self.paused = False
        self._send("loadfile", [path, "replace"])

    def pause(self) -> None:
        self.paused = True
        self._send("set", ["pause", "yes"])

    def resume(self) -> None:
        self.paused = False
        self._send("set", ["pause", "no"])

    def stop(self) -> None:
        self.paused = False
        self._send("stop")

    def is_paused(self) -> bool:
        return self.paused

    def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))
        self._send("set", ["volume", str(self.volume)])

    def get_volume(self) -> int:
        return self.volume

    def is_playing(self) -> bool:
        return self._running and self.proc is not None and self.proc.poll() is None

    def close(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


class PlaybackController:
    """播放队列与模式管理：与具体播放器解耦，便于无硬件测试。"""

    def __init__(
        self,
        player: BasePlayer,
        mode: PlayerMode = PlayerMode.ORDER,
        rng: Optional[random.Random] = None,
    ):
        self.player = player
        self.mode = PlayerMode(mode) if isinstance(mode, str) else mode
        self.rng = rng or random.Random()
        self.queue: List[str] = []
        self.index = -1
        self.shuffle_order: List[int] = []
        self.playlist_name: str = ""  # 当前队列来自哪个歌单（""=单曲/未命名）
        self._stopped = False  # 停止标记：阻止 mpv idle 事件误触自动切歌

    # ---- 队列 ----
    def load(
        self,
        paths: List[str],
        start_index: int = 0,
        autoplay: bool = True,
        playlist_name: str = "",
    ) -> bool:
        if not paths:
            return False
        self._stopped = False  # 新队列加载视为重新开始
        self.queue = list(paths)
        self.playlist_name = playlist_name
        if self.mode == PlayerMode.SHUFFLE:
            self._build_shuffle()
            if 0 <= start_index < len(self.queue):
                # 把指定曲目作为随机起点，保证"播放某歌"能定位到该曲
                self.shuffle_order.remove(start_index)
                self.shuffle_order.insert(0, start_index)
            self.index = self.shuffle_order[0]
        else:
            self.index = start_index % len(self.queue)
        if autoplay:
            self._start_current()
        return True

    def _build_shuffle(self) -> None:
        self.shuffle_order = list(range(len(self.queue)))
        self.rng.shuffle(self.shuffle_order)

    def _start_current(self) -> None:
        if not (0 <= self.index < len(self.queue)):
            return
        path = self.queue[self.index]
        self.player.resume()  # 确保从暂停恢复（唤醒时可能暂停过）
        self.player.play(path)

    def play_index(self, index: int) -> bool:
        """播放队列中的第 index 首。"""
        if not (0 <= index < len(self.queue)):
            return False
        self.index = index
        self._start_current()
        return True

    def reload_queue(self, paths: List[str]) -> bool:
        """用新歌单内容刷新当前队列（不打断播放）。

        保持当前正在播的曲目位置；若当前曲目已不在新列表中，则从第一首继续。
        """
        if not paths:
            return False
        cur = self.get_current()  # 当前播放的路径
        self.queue = list(paths)
        if cur in self.queue:
            self.index = self.queue.index(cur)  # 保持当前曲目位置
        else:
            self.index = 0
        if self.mode == PlayerMode.SHUFFLE:
            self._build_shuffle()
            if self.index in self.shuffle_order:
                self.shuffle_order.remove(self.index)
                self.shuffle_order.insert(0, self.index)
        # 不打断播放：继续播当前曲目（若没有正在播则从头开始）
        if not self.player.is_playing() and cur not in self.queue:
            self._start_current()
        return True

    # ---- 控制 ----
    def has_active_track(self) -> bool:
        """是否有当前活跃曲目（index 有效；stop 后 index=-1 则为 False）。"""
        return self.get_current() is not None

    def is_playing(self) -> bool:
        """是否有当前曲目且正在播放（未暂停）。"""
        return self.has_active_track() and self.player.is_playing()

    def pause(self) -> None:
        self.player.pause()

    def resume(self) -> None:
        """继续播放：若之前被 stop（index=-1），则从头重播当前队列。"""
        if not self.queue:
            return
        if self.index == -1:
            self._stopped = False
            self.index = 0
            self._start_current()
            return
        self.player.resume()

    def stop(self) -> None:
        self._stopped = True  # 标记停止，阻止随后的 idle 事件误触切歌
        self.player.stop()
        self.index = -1

    def next(self) -> None:
        """手动下一首：始终前进（循环包裹）。"""
        if not self.queue:
            return
        n = len(self.queue)
        if self.mode == PlayerMode.SHUFFLE:
            pos = self._shuffle_pos()
            pos = (pos + 1) % n if pos >= 0 else 0
            self.index = self.shuffle_order[pos]
        else:
            self.index = (self.index + 1) % n
        self._start_current()

    def prev(self) -> None:
        if not self.queue:
            return
        n = len(self.queue)
        if self.mode == PlayerMode.SHUFFLE:
            pos = self._shuffle_pos()
            pos = (pos - 1) % n if pos >= 0 else n - 1
            self.index = self.shuffle_order[pos]
        else:
            self.index = (self.index - 1) % n
        self._start_current()

    def _shuffle_pos(self) -> int:
        try:
            return self.shuffle_order.index(self.index)
        except ValueError:
            return -1

    def on_track_end(self) -> None:
        """播放结束回调：按模式自动切歌。"""
        if not self.queue:
            return
        if self._stopped:
            # 刚被 stop：mpv 的 idle 事件不是"播完"，不再切歌
            self._stopped = False
            return
        n = len(self.queue)
        if self.mode == PlayerMode.REPEAT_ONE:
            self._start_current()  # 单曲循环
            return
        if self.mode == PlayerMode.REPEAT_ALL:
            if self.index == n - 1:
                self.index = 0
            else:
                self.index += 1
            self._start_current()
            return
        if self.mode == PlayerMode.ORDER:
            if self.index == n - 1:
                self.player.stop()  # 顺序播完停止
            else:
                self.index += 1
                self._start_current()
            return
        if self.mode == PlayerMode.SHUFFLE:
            pos = self._shuffle_pos()
            if pos < 0 or pos + 1 >= len(self.shuffle_order):
                # 随机序播完：重新洗牌继续（不停止），保证每轮顺序都不同
                self._build_shuffle()
                self.index = self.shuffle_order[0]
                self._start_current()
                return
            self.index = self.shuffle_order[pos + 1]
            self._start_current()

    # ---- 模式 ----
    def set_mode(self, mode: PlayerMode) -> None:
        self.mode = PlayerMode(mode) if isinstance(mode, str) else mode
        if self.mode == PlayerMode.SHUFFLE and self.queue:
            # 重新洗牌，但保持当前歌曲不变（只在下次自动切歌时按新随机序走）
            cur = self.get_current()
            self._build_shuffle()
            if cur and cur in self.queue:
                # 把当前曲目作为随机序起点，保证下一次是随机到的不同歌曲
                self.index = self.queue.index(cur)
                if self.index in self.shuffle_order:
                    self.shuffle_order.remove(self.index)
                    self.shuffle_order.insert(0, self.index)
            # 不调用 _start_current：切换模式不打断当前播放

    def get_current(self) -> Optional[str]:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    # ---- 状态持久化 ----
    def snapshot(self) -> dict:
        """导出可持久化的状态（队列路径、当前索引、模式、歌单名）。"""
        return {
            "queue": list(self.queue),
            "index": self.index,
            "mode": self.mode.value,
            "playlist_name": self.playlist_name,
        }

    def restore(self, state: dict, autoplay: bool = True) -> bool:
        """从持久化状态恢复队列与模式；文件已不存在则清掉。"""
        queue = [p for p in state.get("queue", []) if os.path.exists(p)]
        if not queue:
            return False
        mode = PlayerMode(state.get("mode", "order"))
        idx = int(state.get("index", 0))
        if not (0 <= idx < len(queue)):
            idx = 0
        self.mode = mode
        self.queue = queue
        self.index = idx
        self.playlist_name = state.get("playlist_name", "")
        if self.mode == PlayerMode.SHUFFLE:
            self._build_shuffle()
            if idx in self.shuffle_order:
                self.shuffle_order.remove(idx)
                self.shuffle_order.insert(0, idx)
        if autoplay:
            self._start_current()
        return True
