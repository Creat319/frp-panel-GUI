"""集中管理程序用到的各个路径。

* 源码运行时：程序目录 = 工作区根目录（``frp-panel-windows-amd64.exe`` 所在目录），
  组件库从 ``PyQt-SiliconUI-main`` 目录导入。
* 打包成 exe 后：程序目录 = exe 所在目录（frp-panel 客户端 exe 也应该放在这里），
  组件库已经被打进包里，不再需要额外路径。

界面上一律展示相对路径（:func:`display_path`），避免把本机绝对路径暴露出去。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 是否是 PyInstaller 打包后运行
FROZEN: bool = bool(getattr(sys, "frozen", False))

PACKAGE_DIR: Path = Path(__file__).resolve().parent

if FROZEN:
    # exe 所在目录：配置、frp-panel 客户端都放在这里
    BASE_DIR: Path = Path(sys.executable).resolve().parent
    # 打包后的资源解包目录（组件库、图标等都在这）
    BUNDLE_DIR: Path = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = PACKAGE_DIR.parent
    BUNDLE_DIR = BASE_DIR

# SiliconUI 组件库（源码模式下从仓库目录导入）
SIUI_DIR: Path = BUNDLE_DIR / "PyQt-SiliconUI-main"

# 程序自己的图标资源（打包时会一起带上）
ASSETS_DIR: Path = PACKAGE_DIR / "assets"
LOGO_FILE: Path = ASSETS_DIR / "logo_new.png"

# frp-panel 客户端可执行文件
FRP_EXE_NAME: str = "frp-panel-windows-amd64.exe"
FRP_EXE: Path = BASE_DIR / FRP_EXE_NAME
# 界面上展示的写法，与用户在网页上看到的启动命令保持一致
FRP_EXE_DISPLAY: str = f"./{FRP_EXE_NAME}"

# 配置文件与日志
CONFIG_FILE: Path = BASE_DIR / "frp_client_config.json"
LOG_DIR: Path = BASE_DIR / "logs"

# frp-panel 面板默认地址
DEFAULT_PANEL_URL: str = "http://119.29.227.224:9000/clients"

# 我的世界局域网联机默认端口（仅用于文案提示）
DEFAULT_MC_LAN_PORT: int = 25565


def frp_exe() -> Path:
    """返回 frp-panel 可执行文件路径。"""
    return FRP_EXE


def logo_file() -> Path | None:
    """程序图标文件（找不到返回 None）。"""
    return LOGO_FILE if LOGO_FILE.exists() else None


def display_path(path: Path | str, base: Path | None = None) -> str:
    """把路径转成「相对程序目录」的写法，用于界面展示。

    程序目录内的文件显示成相对路径（例如 ``frp_client_config.json``）；
    确实在程序目录之外的，退回只显示文件名，避免展示本机绝对路径。
    """
    path = Path(path)
    base = base or BASE_DIR
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def ensure_siui_on_path() -> Path | None:
    """源码模式下把组件库目录加入 sys.path，使 `import siui` 可用。

    打包后组件库已经在包内，直接返回 None。
    """
    if FROZEN:
        return None

    path = str(SIUI_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return SIUI_DIR


def describe_layout() -> str:
    """返回一句「程序在哪里、客户端 exe 在哪里」的相对路径描述。"""
    return f"{display_path(BASE_DIR)}"


def open_in_file_manager(path: Path) -> None:
    """在资源管理器中打开目录（仅 Windows / macOS / Linux 常见桌面环境）。"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606 - 用户主动点击
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(path)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception:  # noqa: BLE001 - 打不开就算了
        pass
