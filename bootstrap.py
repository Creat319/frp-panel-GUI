"""程序启动引导：准备 sys.path、QApplication 与全局样式。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from frp_client import paths

_APP_READY = False

# 全局滚动条样式（组件库的滚动区域自己实现滚动条，不受影响）
SCROLLBAR_QSS = """
QScrollBar:vertical { background: transparent; width: 10px; margin: 0px; }
QScrollBar::handle:vertical { background: #4C4554; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #5F5769; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0px; }
QScrollBar::handle:horizontal { background: #4C4554; border-radius: 5px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: #5F5769; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def prepare_environment() -> None:
    """导入 siui 之前必须完成的准备工作。

    组件库在被导入时会读取 Windows 的 DPI 缩放比例并写入 QT_SCALE_FACTOR
    环境变量，而该变量只有在 QApplication 创建之前设置才会生效，
    因此必须在创建 QApplication 之前先导入 siui。
    """
    paths.ensure_siui_on_path()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


def install_numpy_shim() -> bool:
    """让组件库用极简 numpy 替身。

    组件库只拿 numpy 做小数组的加减乘除，但 Windows 上的 numpy 会连带加载
    20 MB 的 OpenBLAS 和 3.5 MB 的 C 扩展。替身实现覆盖了组件库真正用到的接口
    （见 frp_client/numpy_shim.py 与 _dev/test_numpy_shim.py 的差分测试）。

    设环境变量 ``FRP_GUI_REAL_NUMPY=1`` 可以强制用真 numpy（源码调试时用）。
    """
    import os
    import sys

    if os.environ.get("FRP_GUI_REAL_NUMPY"):
        return False
    if "numpy" in sys.modules:
        return False  # 已经有人导入过真的了，别乱换

    try:
        from frp_client import numpy_shim
    except Exception:  # noqa: BLE001
        return False

    sys.modules["numpy"] = numpy_shim
    return True


def install_lazy_iconpack() -> None:
    """让组件库用我们的「惰性图标包」。

    组件库原来的实现会在导入时把 5410 个图标的 SVG 文本（约 7 MB）全读进内存，
    而我们只用其中二三十个。这里在 ``import siui`` 之前把它自己的
    ``siui.gui.icons.parser`` 换成惰性版本，接口完全一致。
    """
    import sys
    import types

    from frp_client import iconpack

    module = types.ModuleType("siui.gui.icons.parser")
    module.GlobalIconPack = iconpack.GlobalIconPack
    module.__doc__ = "惰性图标包（由 frp_client.iconpack 提供）"
    sys.modules["siui.gui.icons.parser"] = module


def import_siui():
    """导入组件库，返回 siui 模块。"""
    prepare_environment()
    install_numpy_shim()
    install_lazy_iconpack()
    import siui  # noqa: PLC0415  (必须在设置环境变量之后再导入)

    return siui


def trim_working_set() -> bool:
    """把闲置内存页换出（Windows 的 EmptyWorkingSet）。

    程序收进托盘后台挂着时，任务管理器里看到的内存会明显下降；
    页并没有丢，只是被换到待机列表，下次操作界面时系统会自动换回来。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.restype = wintypes.BOOL
        return bool(psapi.EmptyWorkingSet(kernel32.GetCurrentProcess()))
    except Exception:  # noqa: BLE001
        return False


def memory_mb() -> float:
    """当前进程的工作集大小（MB），用于日志与自测。"""
    if not sys.platform.startswith("win"):
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(Counters),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                      ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / 1048576
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def patch_library_bugs() -> None:
    """修补组件库里会直接让程序崩溃的地方。

    1. ``SiScrollArea.wheelEvent`` 在「内容高度 == 可视高度」时会做 0 除法，
       numpy 会算出 NaN，随后 ``int(NaN)`` 抛 ValueError。
       页面正好铺满时滚一下鼠标就崩溃，这里改成无需滚动时直接忽略滚轮事件。
    """
    from siui.components.widgets.scrollarea import SiScrollArea

    if getattr(SiScrollArea, "_frp_safe_wheel", False):
        return

    original_wheel_event = SiScrollArea.wheelEvent

    def safe_wheel_event(self, event):
        if self.attachment_.height() <= self.height():
            event.ignore()
            return
        return original_wheel_event(self, event)

    SiScrollArea.wheelEvent = safe_wheel_event
    SiScrollArea._frp_safe_wheel = True


def install_qt_message_filter() -> None:
    """过滤掉组件库/模板带来的无意义 Qt 警告，保留其它信息。"""
    from PyQt5.QtCore import qInstallMessageHandler

    ignored = (
        "Pixmap is a null pixmap",       # 模板里写死的 ./img/logo_new.png 不存在
        "Cannot find font directory",    # 无头模式下 Qt 找不到自带字体目录
        "UpdateLayeredWindowIndirect",   # 隐藏的提示浮层刷新失败，无影响
    )

    def handler(_mode, _context, message):
        if any(text in message for text in ignored):
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(handler)


def install_exception_hook(handler) -> None:
    """安装全局异常钩子，避免 PyQt 在槽函数出错时直接 abort 掉程序。"""
    import traceback

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()
        print(text, file=sys.stderr)
        # 打包成 exe 后没有控制台，顺手落一份日志方便排查
        if paths.FROZEN:
            try:
                with open(paths.BASE_DIR / "frp_client_crash.log", "a", encoding="utf-8") as handle:
                    handle.write(text + "\n")
            except OSError:
                pass
        try:
            handler(text)
        except Exception:  # noqa: BLE001 - 异常处理器自身不能再抛异常
            pass

    sys.excepthook = hook


def create_application(argv: list[str] | None = None):
    """创建（或复用）QApplication，并完成全局字体、图标等初始化。"""
    global _APP_READY

    siui = import_siui()

    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication

    from siui.core import GlobalFont, SiColor, SiGlobal
    from siui.gui import SiFont

    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)

    app.setApplicationName("frp-panel 可视化客户端")
    app.setApplicationDisplayName("frp-panel 可视化客户端")
    app.setFont(SiFont.tokenized(GlobalFont.S_NORMAL))
    app.setStyleSheet(SCROLLBAR_QSS)
    patch_library_bugs()
    install_qt_message_filter()

    logo = paths.logo_file()
    if logo is not None:
        app.setWindowIcon(QIcon(str(logo)))

    if not _APP_READY:
        # 把内置图标包的颜色设置为当前主题的图标色
        SiGlobal.siui.iconpack.setDefaultColor(SiGlobal.siui.colors.fromToken(SiColor.SVG_NORMAL))
        _APP_READY = True

    return app


def icon(name: str, color: str | None = None) -> bytes:
    """从组件库内置图标包中取出一枚 SVG 图标（bytes）。"""
    from siui.core import SiGlobal

    return SiGlobal.siui.iconpack.get(name, color)


def color(token) -> str:
    """取主题色号。"""
    from siui.core import SiGlobal

    return SiGlobal.siui.colors.fromToken(token)


def logo_path() -> Path:
    return paths.LOGO_FILE
