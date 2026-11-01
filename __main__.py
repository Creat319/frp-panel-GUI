"""`python -m frp_client` 的入口。"""

from __future__ import annotations

import sys
import time
import traceback

# 单实例锁需要一直持有到进程结束，所以放在模块级
_INSTANCE_GUARD = None


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception:  # noqa: BLE001 - 打包后没有控制台，错误要落到文件里
        _write_crash_log(traceback.format_exc())
        raise


def _main(argv: list[str] | None = None) -> int:
    global _INSTANCE_GUARD

    arguments = list(argv) if argv is not None else sys.argv[1:]
    take_over = "--take-over" in arguments

    from frp_client.bootstrap import create_application

    app = create_application([sys.argv[0], *arguments])

    from frp_client.single_instance import (
        TAKE_OVER_TIP,
        InstanceGuard,
        clear_show_request,
        kill_other_instances,
        request_show,
        wait_until_consumed,
    )

    guard = InstanceGuard()
    if not guard.acquire():
        # 已经有实例在运行：先请它把窗口显示出来
        request_show()
        if wait_until_consumed():
            return 0  # 旧实例已经把窗口叫出来了，本进程功成身退

        clear_show_request()

        # 旧实例没响应：问一下用户要不要结束它
        if not take_over and not _ask_take_over(TAKE_OVER_TIP):
            return 0

        killed = kill_other_instances()
        if killed == 0:
            # 没有别的进程了（可能刚好退出），再抢一次锁就行
            if not guard.acquire():
                _warn("无法启动", "旧实例没能结束，请到任务管理器里结束 frp-panel-GUI 后再试。")
                return 1
        else:
            for _ in range(20):  # 等系统释放互斥体
                if guard.acquire():
                    break
                time.sleep(0.2)
            else:
                _warn("无法启动", "旧实例已结束，但系统资源还没释放，请稍后再启动一次。")
                return 1

    _INSTANCE_GUARD = guard

    from frp_client.app import create_app_window

    window = create_app_window()
    window.show()
    return app.exec_()


def _ask_take_over(text: str) -> bool:
    """问用户要不要结束卡住的旧实例。"""
    from PyQt5.QtWidgets import QMessageBox

    box = _styled_box("程序已经在运行", text, warning=True)
    restart = box.addButton("结束旧程序并重新启动", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(restart)
    box.exec_()
    return box.clickedButton() is restart


def _warn(title: str, text: str) -> None:
    _styled_box(title, text).exec_()


def _styled_box(title: str, text: str, warning: bool = False):
    from PyQt5.QtWidgets import QMessageBox

    box = QMessageBox()
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning if warning else QMessageBox.Information)
    box.setText(text)
    box.setStyleSheet(
        "QMessageBox { background-color: #25222A; }"
        "QLabel { color: #DFDFDF; }"
        "QPushButton { background-color: #4C4554; color: #DFDFDF;"
        "  border: none; border-radius: 6px; padding: 6px 20px; }"
        "QPushButton:hover { background-color: #5A5263; }"
    )
    return box


def _write_crash_log(text: str) -> None:
    """把启动阶段的异常写到程序目录，方便打包后排错。"""
    try:
        from frp_client import paths

        path = paths.BASE_DIR / "frp_client_crash.log"
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
