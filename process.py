"""frp-panel 客户端进程管理。

负责启动 / 停止子进程、实时读取它的输出（frp-panel 把日志全部写在 stderr），
并支持向它写入数据（内置终端的输入框）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, pyqtSignal

# 进程状态
STATE_IDLE = "idle"            # 未启动
STATE_STARTING = "starting"    # 正在启动
STATE_RUNNING = "running"      # 运行中
STATE_CONNECTED = "connected"  # 已连接上 master
STATE_STOPPING = "stopping"    # 正在停止
STATE_STOPPED = "stopped"      # 已停止
STATE_FAILED = "failed"        # 启动失败

IS_WINDOWS = sys.platform.startswith("win")

# 在 Windows 上隐藏子进程自带的控制台窗口（我们有自己的终端）
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


class _ReaderThread(QThread):
    """在后台线程里逐行读取子进程输出。"""

    lineRead = pyqtSignal(str)
    streamClosed = pyqtSignal()

    def __init__(self, stream, parent=None):
        super().__init__(parent)
        self._stream = stream
        self._stopping = threading.Event()

    def stop(self):
        self._stopping.set()

    def run(self):
        stream = self._stream
        while not self._stopping.is_set():
            try:
                line = stream.readline()
            except (ValueError, OSError):
                break
            if not line:
                break
            self.lineRead.emit(line)
        self.streamClosed.emit()


class FrpClientProcess(QObject):
    """封装 frp-panel 子进程。"""

    lineReceived = pyqtSignal(str)     # 收到一行原始输出（可能带 ANSI 颜色）
    stateChanged = pyqtSignal(str)     # 进程状态变化
    processStarted = pyqtSignal(int)   # 子进程 pid
    processFinished = pyqtSignal(int)  # 退出码
    failed = pyqtSignal(str)           # 启动失败原因

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: subprocess.Popen | None = None
        self._reader: _ReaderThread | None = None
        self._state = STATE_IDLE
        self._argv: list[str] = []

    # ------------------------------------------------------------------ 状态

    def state(self) -> str:
        return self._state

    def isRunning(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def setState(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.stateChanged.emit(state)

    # ------------------------------------------------------------------ 启动

    def start(self, argv: list[str], cwd: str | Path | None = None) -> bool:
        """启动 frp-panel 客户端。返回是否成功发起启动。"""
        if self.isRunning():
            self.failed.emit("内网穿透已经在运行中了。")
            return False

        if not argv:
            self.failed.emit("启动参数为空。")
            return False

        executable = Path(argv[0])
        if not executable.exists():
            self.failed.emit(f"找不到程序文件：{executable}")
            self.setState(STATE_FAILED)
            return False

        self._argv = list(argv)
        environment = os.environ.copy()
        environment.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            self._process = subprocess.Popen(
                argv,
                cwd=str(cwd or executable.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,          # frp-panel 的日志全部在 stderr
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                env=environment,
            )
        except OSError as error:
            self._process = None
            self.setState(STATE_FAILED)
            self.failed.emit(f"启动失败：{error}")
            return False

        self._reader = _ReaderThread(self._process.stdout, self)
        self._reader.lineRead.connect(self.lineReceived)
        self._reader.streamClosed.connect(self._onStreamClosed)
        self._reader.start()

        self.setState(STATE_STARTING)
        self.processStarted.emit(self._process.pid)
        return True

    # ------------------------------------------------------------------ 停止

    def stop(self, timeout: float = 6.0) -> None:
        """停止子进程（连同它拉起的 frpc 子进程一起结束）。"""
        process = self._process
        if process is None:
            self.setState(STATE_IDLE)
            return

        if process.poll() is None:
            self.setState(STATE_STOPPING)
            self._terminate_tree(process)

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:  # noqa: BLE001 - 兜底，保证不会卡住界面
                pass

        self._closeStreams()
        if self._reader is not None:
            self._reader.stop()
            self._reader.wait(2000)
            self._reader = None

        exit_code = process.poll()
        self._process = None
        self.setState(STATE_STOPPED)
        if exit_code is not None:
            self.processFinished.emit(exit_code)

    def _terminate_tree(self, process: subprocess.Popen) -> None:
        """结束整棵进程树，避免 frp-panel 拉起的 frpc 继续占用端口。"""
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10,
                    check=False,
                )
                return
            except Exception:  # noqa: BLE001 - 退回 terminate
                pass

        try:
            process.terminate()
        except Exception:  # noqa: BLE001
            pass

    def _closeStreams(self) -> None:
        process = self._process
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _onStreamClosed(self) -> None:
        process = self._process
        if process is None:
            return
        code = process.poll()
        if code is None:
            return
        if self._state not in (STATE_STOPPING, STATE_STOPPED):
            self.setState(STATE_FAILED if code != 0 else STATE_STOPPED)
        self.processFinished.emit(code)

    # ------------------------------------------------------------------ 交互

    def send(self, text: str) -> bool:
        """把一行文本写入子进程的标准输入。"""
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(text.rstrip("\n") + "\n")
            process.stdin.flush()
            return True
        except (BrokenPipeError, ValueError, OSError):
            return False
