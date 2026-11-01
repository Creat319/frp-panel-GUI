"""单实例保护 + 唤醒已有实例。

程序最小化到托盘后会一直在后台运行，用户很容易再点一次启动图标。
这里用「命名互斥体」判断是否已经有实例在跑，避免出现两个托盘图标、
甚至两个 frp-panel 客户端抢同一条隧道。

被拦住时不能只让用户自己去托盘里找（托盘图标可能被系统折叠进「隐藏的图标」，
甚至根本没显示出来），所以再补一条**基于文件的唤醒通道**：

* 第二个实例写一个 ``frp_client_show.request`` 文件然后等结果；
* 运行中的实例每秒看一眼这个文件，看到就把窗口显示出来并删掉它；
* 第二个实例等 1~2 秒发现文件没被消费，说明旧实例没响应，
  就提示用户「结束旧程序并重新启动」，直接兜底。

用文件而不是命名管道，是因为文件通道在各种受限环境下都能用。

Windows 下的互斥体用 CreateMutexW（内核对象，不依赖命名管道）；
其它平台不做单实例限制，直接放行。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from frp_client import paths

MUTEX_NAME = "Local\\frp-panel-client-gui-single-instance"

# 「把窗口叫出来」请求文件
WAKE_FILE: Path = paths.BASE_DIR / "frp_client_show.request"

# 第二个实例最多等多久，判断旧实例有没有响应
WAKE_TIMEOUT = 2.5


class InstanceGuard:
    """进程级单实例锁，创建成功后需要一直持有，直到进程退出。"""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle = None

    def acquire(self) -> bool:
        """返回 True 表示当前是第一个实例；False 表示已经有实例在运行。"""
        if not sys.platform.startswith("win"):
            return True

        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            create_mutex.restype = wintypes.HANDLE

            handle = create_mutex(None, False, self.name)
            if not handle:
                return True  # 出问题就放行，不要挡住用户

            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False

            self._handle = handle
            return True
        except Exception:  # noqa: BLE001 - 单实例只是锦上添花，失败就放行
            return True

    def release(self) -> None:
        if self._handle is None or not sys.platform.startswith("win"):
            return
        try:
            import ctypes

            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._handle = None


# --------------------------------------------------------------------------- 唤醒通道
#
# 请求文件里写一个命令：
#   show（默认）—— 把窗口显示出来
#   hide        —— 走一次「点 × 」的流程（收进托盘），用于自动化测试
# 第二个实例只写 show，写别的命令是给自测脚本用的。

REQUEST_SHOW = "show"
REQUEST_HIDE = "hide"


def request(command: str = REQUEST_SHOW) -> None:
    """（第二个实例）请求已有实例做点事情。"""
    try:
        WAKE_FILE.write_text(command or REQUEST_SHOW, encoding="utf-8")
    except OSError:
        pass


def request_show() -> None:
    request(REQUEST_SHOW)


def request_hide() -> None:
    request(REQUEST_HIDE)


def take_request() -> str | None:
    """（运行中的实例）取出请求命令并删掉文件；没有请求返回 None。

    顺手去掉可能存在的 BOM、统一小写，免得写文件的一方带了编码前缀就识别不出来。
    """
    if not WAKE_FILE.exists():
        return None
    for _ in range(3):
        try:
            content = WAKE_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        try:
            WAKE_FILE.unlink()
        except OSError:
            time.sleep(0.05)
            continue
        content = content.lstrip("\ufeff").strip().lower()
        return content or REQUEST_SHOW
    return None


def consume_show_request() -> bool:
    """（运行中的实例）有请求就消费掉并返回 True（兼容旧接口）。"""
    return take_request() is not None


def wait_until_consumed(timeout: float = WAKE_TIMEOUT) -> bool:
    """（第二个实例）等待旧实例消费掉请求文件，返回是否成功。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not WAKE_FILE.exists():
            return True
        time.sleep(0.1)
    return False


def clear_show_request() -> None:
    try:
        WAKE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _command_line(pid: int) -> str:
    """取某个进程的命令行（失败就返回空串，宁可不动手）。"""
    import subprocess

    creation_flags = 0x08000000 if sys.platform.startswith("win") else 0
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, text=True, errors="replace",
            creationflags=creation_flags, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


def other_instance_pids() -> list[int]:
    """找出其它正在运行的同类进程（不含自己）。

    打包后进程名是 frp-panel-GUI.exe，很唯一；源码运行时进程名是 python.exe，
    这时额外按命令行过滤，避免误伤别的 Python 程序。
    """
    import os
    import subprocess

    image = Path(sys.executable).name
    creation_flags = 0x08000000 if sys.platform.startswith("win") else 0
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace",
            creationflags=creation_flags, check=False)
    except OSError:
        return []

    candidates: list[int] = []
    for line in (result.stdout or "").splitlines():
        parts = [part.strip('" ') for part in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            pid = int(parts[1])
            if pid != os.getpid():
                candidates.append(pid)

    if paths.FROZEN:
        return candidates  # exe 名字唯一，直接就是同类进程

    # 源码模式：靠命令行里的 frp_client / run_frp_client 区分
    matched: list[int] = []
    for pid in candidates:
        command_line = _command_line(pid).lower()
        if command_line and ("frp_client" in command_line or "run_frp_client" in command_line):
            matched.append(pid)
    return matched


def kill_other_instances() -> int:
    """结束其它实例（含它拉起的 frp-panel 客户端），返回结束掉的进程数。

    打包后直接用 ``taskkill /IM`` + PID 过滤，一条命令搞定，不依赖 tasklist；
    源码模式下进程名是 python.exe，只能先按命令行筛出目标再逐个结束。
    """
    import os
    import subprocess

    creation_flags = 0x08000000 if sys.platform.startswith("win") else 0

    if paths.FROZEN:
        image = Path(sys.executable).name
        before = other_instance_pids()
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", image, "/FI", f"PID ne {os.getpid()}"],
            capture_output=True, text=True, errors="replace",
            creationflags=creation_flags, check=False)
        output = (result.stdout or "") + (result.stderr or "")
        if "denied" in output.lower() or "拒绝" in output:
            return 0
        return len(before)

    killed = 0
    for pid in other_instance_pids():
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=creation_flags, check=False)
        killed += 1
    return killed


# --------------------------------------------------------------------------- 文案

ALREADY_RUNNING_TIP = (
    "frp-panel 可视化客户端已经在运行了，已经尝试把它叫到前台。\n\n"
    "如果窗口没有出现，说明那个实例可能卡住了（或者它的托盘图标被系统折叠了），"
    "可以选「结束旧程序并重新启动」。"
)

TAKE_OVER_TIP = (
    "检测到已经有一个实例在运行，但它没有响应（窗口没有出现）。\n\n"
    "可以结束那个旧的实例并重新启动本程序。\n"
    "注意：如果它正在做内网穿透，结束它会让朋友掉线。"
)
