"""后台 HTTP 客户端。

- 在工作线程中轮询 GET /api/state 并发出 `state_changed` 信号；
- 控制动作（喂食/灯/过滤/…）先进队列，在工作线程里 POST /api/control；
- 若后台未运行且允许自启动，则用当前 Python 解释器拉起 `app.py`；
- 退出时只终止由本客户端自己拉起的后台进程。
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests
from PySide6.QtCore import QObject, Signal

AQUARIUM_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PORT = int(os.environ.get("AQUARIUM_PORT", "10000"))


class BackendClient(QObject):
    state_changed = Signal(dict)          # 收到一次完整快照
    connection_changed = Signal(bool)     # 连接状态变化
    notice = Signal(str)                  # 面向用户的提示文案

    def __init__(self, port: int | None = None) -> None:
        super().__init__()
        self.port = port or DEFAULT_PORT
        self.base = f"http://127.0.0.1:{self.port}"

        self._queue: collections.deque[tuple[str, Any]] = collections.deque()
        self._qlock = threading.Lock()
        self._stop = threading.Event()
        self._spawn_allowed = True
        self._proc: subprocess.Popen | None = None
        self._spawned_by_us = False
        self._connected = False
        self._thread: threading.Thread | None = None

    # ---------------- 对外 API ----------------
    def start(self) -> None:
        """启动（或重启）轮询线程。"""
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop, name="aquarium-backend-client", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._spawned_by_us and self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def call(self, action: str, value: Any = None) -> None:
        """发送一个控制动作（线程安全，异步生效）。"""
        with self._qlock:
            self._queue.append((action, value))

    def request_reconnect(self, spawn: bool = True) -> None:
        """用户点击“重试”时：重新开始连接，并允许再次拉起后台。"""
        self._spawn_allowed = spawn
        self.start()

    # ---------------- 内部实现 ----------------
    def _health(self) -> bool:
        try:
            r = requests.get(f"{self.base}/api/health", timeout=0.8)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def _spawn_backend(self) -> None:
        self.notice.emit(f"后台未运行，正在自动启动（端口 {self.port}）…")
        env = {**os.environ, "AQUARIUM_PORT": str(self.port)}
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=str(AQUARIUM_DIR),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._spawned_by_us = True
        except OSError as exc:  # 找不到解释器等
            self.notice.emit(f"启动后台失败：{exc}")

    def _ensure_backend(self) -> bool:
        """确保后台可用；必要时拉起并等待最多 20 秒。"""
        if self._health():
            return True
        if not self._spawn_allowed:
            return False
        # 已有一个仍在运行的子进程（可能正在启动中），先等它
        if self._proc is not None and self._proc.poll() is None:
            return False
        self._spawn_backend()
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if self._stop.is_set():
                return False
            if self._health():
                return True
            time.sleep(0.5)
        self.notice.emit(f"后台启动超时，请检查端口 {self.port} 是否被占用。")
        return False

    def _set_connected(self, ok: bool) -> None:
        if ok != self._connected:
            self._connected = ok
            self.connection_changed.emit(ok)

    def _post_pending(self) -> dict | None:
        """把队列里的控制动作逐个 POST，返回最后一个快照。"""
        snapshot: dict | None = None
        while True:
            with self._qlock:
                if not self._queue:
                    break
                action, value = self._queue.popleft()
            try:
                r = requests.post(
                    f"{self.base}/api/control",
                    json={"action": action, "value": value},
                    timeout=3,
                )
                r.raise_for_status()
                snapshot = r.json()
                self.state_changed.emit(snapshot)
            except requests.RequestException:
                self._set_connected(False)
                return None
        return snapshot

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._connected:
                ok = self._ensure_backend()
                self._set_connected(ok)
                if not ok:
                    self._stop.wait(2.0)
                    continue

            snapshot = self._post_pending()
            if snapshot is None and not self._connected:
                continue  # 控制失败导致断线，回到重连逻辑

            try:
                r = requests.get(f"{self.base}/api/state", timeout=3)
                r.raise_for_status()
                self.state_changed.emit(r.json())
                self._set_connected(True)
            except requests.RequestException:
                self._set_connected(False)

            self._stop.wait(0.6)
