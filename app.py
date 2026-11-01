"""主窗口：把命令行解析、子进程管理和界面串起来。"""

from __future__ import annotations

import time
import webbrowser

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QDesktopWidget,
    QMenu,
    QSystemTrayIcon,
)

from frp_client import appearance, bootstrap
from frp_client import config as config_module
from frp_client import paths
from frp_client.ansi import strip_ansi
from frp_client.command import CommandParseError, masked_display, parse_command
from frp_client.guide import GuideOverlay
from frp_client.page_appearance import AppearancePage
from frp_client.pages import DashboardPage, HelpPage, TerminalPage
from frp_client.process import (
    STATE_CONNECTED,
    STATE_FAILED,
    STATE_IDLE,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    STATE_STOPPING,
    FrpClientProcess,
)
from frp_client.widgets import ActionButton, status_text

# frpc 连接成功的日志特征（frp-panel 会把 frpc 的日志转发到同一个输出里）
SUCCESS_PATTERNS = ("login to server success", "start proxy success", "start frpc", "frpc started")
# 这些行里也含 success，但并不代表隧道可用
SUCCESS_EXCLUDE = ("register envent",)

COMMAND_DEBOUNCE_MS = 250
# 外观设置改动后延迟保存的时间，避免拖滑块时疯狂写文件
APPEARANCE_SAVE_DELAY_MS = 800


def tray_menu_qss() -> str:
    """托盘菜单样式（跟随外观设置）。"""
    pal = appearance.current().palette()
    return (
        f"QMenu {{ background-color: {pal['card_bg']}; color: {pal['text_b']};"
        f"  border: 1px solid {pal['border']}; border-radius: 8px; padding: 6px; }}"
        f"QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 5px; }}"
        f"QMenu::item:selected {{ background-color: {pal['hover_bg']}; }}"
        f"QMenu::item:disabled {{ color: {pal['text_e']}; }}"
        f"QMenu::separator {{ height: 1px; background: {pal['border']}; margin: 5px 8px; }}"
    )


def create_app_window(config: dict | None = None):
    """创建基于 SiliconUI 应用模板的主窗口。

    窗口类在函数内部定义，这样可以保证组件库（siui）已经完成路径与 DPI 初始化。
    """
    from siui.core import SiGlobal
    from siui.templates.application.application import SiliconApplication

    class FrpPanelClientWindow(SiliconApplication):
        """frp-panel 可视化客户端主窗口。"""

        def __init__(self):
            super().__init__()

            self.config = config or config_module.load()
            # 先把外观设置装好，后面创建的控件一开始就是正确的配色 / 字体
            self.appearance = appearance.init(self.config.get("appearance"))
            self.process = FrpClientProcess(self)
            self.parsed = None
            self.connected = False
            self.error_count = 0
            self.started_at: float | None = None
            self.expired_hint_shown = False
            self.user_stopped = False
            self._ever_shown = False

            self.setWindowTitle("frp-panel 可视化客户端")
            self.layerMain().setTitle("frp-panel 可视化客户端")
            logo = paths.logo_file()
            if logo is not None:
                self.setWindowIcon(QIcon(str(logo)))
                self.layerMain().app_icon.load(str(logo))

            self._build_pages()
            self._build_guide()
            self._wrap_overlay()
            self._build_tray()
            self._wire_signals()
            self._restore_config()

            self.appearance.apply(self)
            SiGlobal.siui.reloadAllWindowsStyleSheet()
            self._print_banner()
            bootstrap.install_exception_hook(self._on_unhandled_exception)

            # 首次启动自动播放新手引导
            QTimer.singleShot(700, self._maybe_show_guide)

            if not self.dashboard.mc_confirmed():
                self.notify("先开启《我的世界》局域网",
                            "顺序：先开局域网，再启动穿透",
                            "单人游戏 → ESC → 对局域网开放")

        # -------------------------------------------------------------- 新手引导

        def _build_guide(self) -> None:
            self.guide = GuideOverlay(self)
            self.guide.finished.connect(self._on_guide_finished)
            self.guide.stepChanged.connect(self.layerMain().setPage)

        def _maybe_show_guide(self) -> None:
            if not self.config.get("guide_done"):
                self.show_guide()

        def show_guide(self) -> None:
            """播放（或重播）新手引导。"""
            self.guide.reposition()
            self.guide.start()
            self.message("开始播放新手引导，随时可以点「跳过引导」或按 Esc 跳过。", "accent")

        def _on_guide_finished(self, completed: bool) -> None:
            self.config["guide_done"] = True
            self._save_config()
            if completed:
                self.message("新手引导已看完，开始用吧！先开《我的世界》局域网，再粘贴启动命令。",
                             "log_success")
                self.notify("引导结束", "祝开黑愉快", "有问题可以看「使用帮助」")
            else:
                self.message("已跳过新手引导，可以在这里的「使用帮助」页面重新播放。", "text_e")

        def _on_guide_escape(self) -> bool:
            """Esc：引导开着就跳过引导。"""
            if self.guide is not None and self.guide.isVisible():
                self.guide.skip()
                return True
            return False

        # -------------------------------------------------------------- 构建

        def _build_pages(self) -> None:
            self.dashboard = DashboardPage(
                self, panel_url=self.config.get("panel_url", paths.DEFAULT_PANEL_URL))
            self.terminal_page = TerminalPage(self)
            self.appearance_page = AppearancePage(self)
            self.help_page = HelpPage(self)

            self.layerMain().addPage(
                self.dashboard, icon=SiGlobal.siui.iconpack.get("ic_fluent_rocket_regular"),
                hint="启动面板", side="top")
            self.layerMain().addPage(
                self.terminal_page, icon=SiGlobal.siui.iconpack.get("ic_fluent_window_dev_tools_regular"),
                hint="内置终端", side="top")
            self.layerMain().addPage(
                self.appearance_page, icon=SiGlobal.siui.iconpack.get("ic_fluent_paint_brush_regular"),
                hint="外观与设置", side="top")
            self.layerMain().addPage(
                self.help_page, icon=SiGlobal.siui.iconpack.get("ic_fluent_question_circle_regular"),
                hint="使用帮助", side="bottom")
            self.layerMain().setPage(0)

        def _wrap_overlay(self) -> None:
            """模板自带的浮层会在改变窗口大小时弹出演示提示，这里把它改造成通知浮层。"""
            overlay = self.layer_overlays.state_change_overlay
            self._overlay = overlay
            self._overlay_set_content = overlay.setContent
            overlay.setContent = lambda *args, **kwargs: None
            overlay.fade_out_timer.stop()
            overlay.expand(0)
            overlay.on_opacity_changed(0.0)

        # -------------------------------------------------------------- 托盘

        def _build_tray(self) -> None:
            """创建托盘图标：关闭窗口时程序缩到托盘，右键可以结束穿透或退出。"""
            self._quitting = False
            self._tray_hint_shown = False
            self._tray = None
            self._tray_menu = None

            if not QSystemTrayIcon.isSystemTrayAvailable():
                self.message("当前系统没有可用的托盘区域，关闭窗口会改成最小化到任务栏。", "log_warning")
                self._trace("托盘不可用：isSystemTrayAvailable() = False")
                return

            icon = self._tray_icon()
            if icon.isNull():
                # 图标拿不到就别缩托盘了，否则用户会「关掉就找不回来」
                self.message("托盘图标加载失败，关闭窗口会改成最小化到任务栏。", "log_warning")
                self._trace("托盘图标为空（logo 和内置图标都没取到）")
                return

            # 关掉「最后一个窗口关闭就退出」，改成由托盘菜单决定是否退出
            QApplication.setQuitOnLastWindowClosed(False)

            self._tray = QSystemTrayIcon(icon, self)
            self._tray.setToolTip("frp-panel 可视化客户端")

            menu = QMenu()
            menu.setStyleSheet(tray_menu_qss())
            self._tray_menu_qss_target = menu

            self._tray_status_action = menu.addAction("状态：未启动")
            self._tray_status_action.setEnabled(False)
            menu.addSeparator()
            menu.addAction("显示主界面", self.show_window)
            menu.addAction("窗口设置…", self.open_settings)
            self._tray_start_action = menu.addAction("启动内网穿透", self.start)
            self._tray_stop_action = menu.addAction("结束穿透", self.stop)
            menu.addSeparator()
            menu.addAction("退出", self.quit_app)

            self._tray_menu = menu
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()

            self._update_tray_state(STATE_IDLE)
            self._trace(f"托盘已创建：visible={self._tray.isVisible()} icon={icon.isNull()}")

        def _tray_icon(self) -> QIcon:
            """托盘图标：程序自带 logo 优先，其次组件库内置图标。"""
            logo = paths.logo_file()
            if logo is not None:
                icon = QIcon(str(logo))
                if not icon.isNull():
                    return icon

            try:
                from siui.core import SiGlobal

                return SiGlobal.siui.iconpack.toIcon(
                    "ic_fluent_plug_connected_regular", QSize(64, 64), "#B07CC6")
            except Exception:  # noqa: BLE001
                return QIcon()

        def _on_tray_activated(self, reason) -> None:
            self._trace(f"tray activated reason={reason}")
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
                self.show_window()

        def show_window(self) -> None:
            """从托盘（或最小化状态）恢复主界面。"""
            self._trace("show_window() 被调用")
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def open_settings(self) -> None:
            """打开「外观与设置」页（托盘菜单里用）。"""
            self.show_window()
            self.layerMain().setPage(2)

        def _trim_if_background(self) -> None:
            """只在窗口不在前台时回收内存，避免影响正在操作时的流畅度。"""
            if not self.isVisible() or self.isMinimized():
                self._trim()

        def _trim(self) -> None:
            """把闲置内存页换出（Windows EmptyWorkingSet）。"""
            before = bootstrap.memory_mb()
            if bootstrap.trim_working_set():
                self._trace(f"回收内存：{before:.1f} MB -> {bootstrap.memory_mb():.1f} MB")

        def _poll_wake_request(self, take) -> None:
            """处理第二个实例留下的请求：叫出窗口，或者按关闭流程收进托盘。"""
            from frp_client.single_instance import REQUEST_HIDE

            command = (take() or "").lower()
            if not command:
                return

            if command == REQUEST_HIDE:
                self._trace("收到 hide 请求，执行关闭流程")
                self.close()  # 和点右上角 × 完全一致
                return

            self._trace("收到 show 请求，把窗口叫到前台")
            self.show_window()
            self.message("已经有一个实例在运行，这里把它的窗口叫到了前台。", "accent")

        def _update_tray_state(self, state: str) -> None:
            if self._tray is None:
                return

            running = state in (STATE_STARTING, STATE_RUNNING, STATE_CONNECTED, STATE_STOPPING)
            text = status_text(state)

            self._tray_start_action.setEnabled(not running)
            self._tray_stop_action.setEnabled(running)
            self._tray_status_action.setText(f"状态：{text}")
            self._tray.setToolTip(f"frp-panel 可视化客户端 · {text}")

        def _notify_minimized_to_tray(self) -> None:
            self.message("窗口已收进系统托盘，程序继续在后台运行。", "accent")
            if self._tray_hint_shown or self._tray is None:
                return
            self._tray_hint_shown = True
            self._tray.showMessage(
                "程序仍在后台运行",
                "已收进系统托盘。Windows 11 可能把新图标折叠在托盘的「显示隐藏的图标」里；"
                "再双击一次程序图标也能把窗口叫回来。",
                QSystemTrayIcon.Information,
                6000)

        def quit_app(self) -> None:
            """托盘菜单里的「退出」：真正退出程序。"""
            self._quitting = True
            self.close()
            QApplication.instance().quit()

        def _wire_signals(self) -> None:
            self.dashboard.startRequested.connect(self.start)
            self.dashboard.stopRequested.connect(self.stop)
            self.dashboard.openPanelRequested.connect(self.open_panel)
            self.dashboard.pasteRequested.connect(self.paste_from_clipboard)
            self.dashboard.mcConfirmedChanged.connect(self._on_mc_confirmed)
            self.help_page.startGuideRequested.connect(self.show_guide)

            self.terminal_page.startRequested.connect(self.start)
            self.terminal_page.stopRequested.connect(self.stop)

            for terminal in self.terminals():
                terminal.inputSubmitted.connect(self._on_terminal_input)
                terminal.localCommand.connect(self._on_local_command)

            self.process.lineReceived.connect(self._on_line)
            self.process.stateChanged.connect(self._on_state_changed)
            self.process.processStarted.connect(self._on_process_started)
            self.process.processFinished.connect(self._on_process_finished)
            self.process.failed.connect(self._on_failed)

            self._parse_timer = QTimer(self)
            self._parse_timer.setSingleShot(True)
            self._parse_timer.setInterval(COMMAND_DEBOUNCE_MS)
            self._parse_timer.timeout.connect(lambda: self.refresh_preview(show_errors=False))
            self.dashboard.commandEdited.connect(lambda _text: self._parse_timer.start())

            self._uptime_timer = QTimer(self)
            self._uptime_timer.setInterval(1000)
            self._uptime_timer.timeout.connect(self._update_status_detail)
            self._uptime_timer.start()

            # 第二个实例会写一个请求文件，这里盯着它：
            # show → 把窗口叫出来；hide → 走一次「点 ×」的流程（收进托盘）
            from frp_client.single_instance import (
                REQUEST_HIDE,
                clear_show_request,
                take_request,
            )

            clear_show_request()
            self._wake_timer = QTimer(self)
            self._wake_timer.setInterval(700)
            self._wake_timer.timeout.connect(lambda: self._poll_wake_request(take_request))
            self._wake_timer.start()

            # 挂后台（收进托盘 / 最小化）时定期把闲置内存页换出，
            # 任务管理器里看到的内存占用会明显下降
            self._trim_timer = QTimer(self)
            self._trim_timer.setInterval(60_000)
            self._trim_timer.timeout.connect(self._trim_if_background)
            self._trim_timer.start()
            QTimer.singleShot(20_000, self._trim)  # 启动稳定后先回收一次

            self.appearance.changed.connect(self._on_appearance_changed)

            self._appearance_save_timer = QTimer(self)
            self._appearance_save_timer.setSingleShot(True)
            self._appearance_save_timer.setInterval(APPEARANCE_SAVE_DELAY_MS)
            self._appearance_save_timer.timeout.connect(self._save_config)

        # -------------------------------------------------------------- 外观

        def _on_appearance_changed(self, _key: str = "*") -> None:
            """外观设置变了：立刻应用到界面，稍后写入配置文件。"""
            self.appearance.apply(self)
            SiGlobal.siui.reloadAllWindowsStyleSheet()
            if self._tray_menu is not None:
                self._tray_menu.setStyleSheet(tray_menu_qss())
            self._appearance_save_timer.start()

        def _restore_config(self) -> None:
            self._restoring = True
            size = self.config.get("window_size") or [1300, 850]
            self.setMinimumSize(1080, 700)
            self.resize(int(size[0]), int(size[1]))

            position = self.config.get("window_pos")
            if position:
                x, y = int(position[0]), int(position[1])
                if QDesktopWidget().availableGeometry().contains(x + 120, y + 60):
                    self.move(x, y)

            command = self.config.get("command") or ""
            if command:
                self.dashboard.set_command_text(command)
            self.dashboard.mc_checkbox.setChecked(bool(self.config.get("mc_confirmed")))
            if command:
                self.refresh_preview(show_errors=False)
            self._update_buttons(STATE_IDLE)
            self._update_tray_state(STATE_IDLE)
            self._restoring = False

            # 首次运行就生成一份默认配置，用户一眼能看到配置文件在哪
            if not paths.CONFIG_FILE.exists():
                self._save_config()

        # -------------------------------------------------------------- 工具

        def terminals(self):
            return (self.dashboard.terminal, self.terminal_page.terminal)

        def log(self, line: str) -> None:
            for terminal in self.terminals():
                terminal.append_raw(line)

        def message(self, text: str, color_code: str = "#8C7FA8", prefix: str = "[GUI]") -> None:
            for terminal in self.terminals():
                terminal.append_message(text, color_code, prefix)

        def notify(self, title: str, subtitle: str = "", tip: str = "") -> None:
            """提示用户：窗口在前台时用浮层，窗口收进托盘时用托盘气泡。"""
            window_hidden = self._ever_shown and ((not self.isVisible()) or self.isMinimized())
            if window_hidden and self._tray is not None:
                detail = " · ".join(part for part in (subtitle, tip) if part)
                self._tray.showMessage(title, detail or title, QSystemTrayIcon.Information, 5000)
                return

            try:
                self._overlay_set_content(title, subtitle, tip)
            except Exception:  # noqa: BLE001 - 提示失败不影响主流程
                pass

        # -------------------------------------------------------------- 命令

        def refresh_preview(self, show_errors: bool = False) -> None:
            text = self.dashboard.command_text()
            if not text.strip():
                self.parsed = None
                self.dashboard.show_parse_result(None)
                return

            try:
                command = parse_command(text)
            except CommandParseError as error:
                self.parsed = None
                self.dashboard.show_parse_result(None, error=str(error))
                if show_errors:
                    self.notify("命令无法识别", "请查看第 2 步的提示", "回网页重新复制启动命令")
                    self.message(f"命令解析失败：{error}", "log_error")
                return

            self.parsed = command
            details = []
            if command.client_id:
                details.append(f"客户端 ID：{command.client_id}")
            if command.api_url:
                details.append(f"面板地址：{command.api_url}")
            if command.rpc_url:
                details.append(f"RPC 地址：{command.rpc_url}")
            self.dashboard.show_parse_result(command.display, "　|　".join(details))

            if command.panel_url and self.dashboard.panel_url() in ("", paths.DEFAULT_PANEL_URL):
                self.dashboard.set_panel_url(command.panel_url)
                self._save_config()

        def paste_from_clipboard(self) -> None:
            text = QApplication.clipboard().text()
            if not text.strip():
                self.message("剪贴板里没有文本。", "log_warning")
                self.notify("剪贴板是空的", "请先在网页上复制启动命令", "")
                return
            self.dashboard.set_command_text(text.strip())
            self.refresh_preview(show_errors=True)
            if self.parsed is not None:
                self.message("已从剪贴板粘贴启动命令。", "log_success")

        def open_panel(self, url: str) -> None:
            url = (url or paths.DEFAULT_PANEL_URL).strip()
            if not url.lower().startswith(("http://", "https://")):
                url = "http://" + url
            try:
                webbrowser.open(url)
                self.message(f"已在浏览器中打开 {url}", "log_success")
            except Exception as error:  # noqa: BLE001
                self.message(f"打开浏览器失败：{error}", "log_error")

        # -------------------------------------------------------------- 启动/停止

        def start(self) -> None:
            if self.process.isRunning():
                self.message("内网穿透已经在运行了，无需重复启动。", "log_warning")
                self.notify("已经在运行", "无需重复启动", "")
                return

            if not self.dashboard.command_text().strip():
                self.message("请先粘贴从网页复制的启动命令。", "log_error")
                self.notify("缺少启动命令", "请先在第 2 步粘贴命令", "面板 → 客户端页面 → 复制启动命令")
                self.layerMain().setPage(0)
                return

            self.refresh_preview(show_errors=True)
            if self.parsed is None:
                self.layerMain().setPage(0)
                return

            if not self.dashboard.mc_confirmed():
                self.message("请先在《我的世界》中开启局域网世界，再启动内网穿透。", "log_warning")
                self.notify("请先开《我的世界》局域网",
                            "先开局域网，再启动穿透",
                            "单人游戏 → ESC → 对局域网开放")
                self.layerMain().setPage(0)
                return

            self.error_count = 0
            self.connected = False
            self.expired_hint_shown = False
            self.user_stopped = False

            command = self.parsed
            self.message(f"执行命令：{masked_display(command)}（密钥已打码）")
            self.message(f"工作目录：{paths.BASE_DIR}")

            if self.process.start(command.argv, cwd=paths.BASE_DIR):
                self.message("已启动 frp-panel 客户端，正在连接 master…", "log_success")

        def stop(self) -> None:
            if not self.process.isRunning():
                if self.process.state() != STATE_IDLE:
                    self.process.stop()
                self.message("当前没有正在运行的内网穿透进程。", "log_warning")
                return
            self.message("正在停止内网穿透…", "log_warning")
            self.notify("正在停止", "内网穿透即将断开", "")
            self.user_stopped = True
            self.process.stop()
            self.message("内网穿透已停止。", "log_success")

        # -------------------------------------------------------------- 进程事件

        def _on_process_started(self, pid: int) -> None:
            self.started_at = time.time()
            self.message(f"客户端进程已启动，PID = {pid}", "log_success")

        def _on_line(self, raw: str) -> None:
            self.log(raw)

            if self.process.state() == STATE_STARTING:
                self.process.setState(STATE_RUNNING)

            lowered = strip_ansi(raw).lower()

            if "error" in lowered or "cannot" in lowered:
                self.error_count += 1

            if "record not found" in lowered and not self.expired_hint_shown:
                self.expired_hint_shown = True
                self.message("客户端 ID 或密钥已失效（record not found），请回网页重新复制启动命令。", "log_error")
                self.notify("命令可能已失效", "record not found", "回网页重新复制启动命令")

            if not self.connected:
                matched = any(pattern in lowered for pattern in SUCCESS_PATTERNS)
                if matched or ("success" in lowered and not any(x in lowered for x in SUCCESS_EXCLUDE)):
                    self.connected = True
                    self.process.setState(STATE_CONNECTED)
                    self.message("已连接 master，内网穿透通道建立成功。", "log_success")
                    self.notify("内网穿透已就绪", "已连接 master", "把公网地址发给朋友吧")

            self._update_status_detail()

        def _on_state_changed(self, state: str) -> None:
            self.dashboard.set_state(state, self._detail_text(state))
            self.terminal_page.set_state(state)
            self._update_buttons(state)
            self._update_tray_state(state)

        def _on_process_finished(self, code: int) -> None:
            if self.user_stopped:
                self.message("客户端进程已结束（由本程序停止）。", "text_e")
            else:
                self.message(f"客户端进程已退出，退出码 {code}。", "log_warning" if code else "text_e")
                if code != 0:
                    self.notify("客户端已退出", f"退出码 {code}", "可以查看终端里的日志")

        def _on_failed(self, reason: str) -> None:
            self.message(reason, "log_error")
            self.notify("启动失败", reason, "请检查命令与程序文件")

        # -------------------------------------------------------------- 状态刷新

        def _detail_text(self, state: str) -> str:
            if state == STATE_IDLE:
                return "还没有启动内网穿透。"
            if state == STATE_STARTING:
                return "正在启动客户端进程…"
            if state in (STATE_RUNNING, STATE_CONNECTED):
                parts = []
                if self.process.pid():
                    parts.append(f"进程 PID {self.process.pid()}")
                if self.started_at:
                    parts.append(f"已运行 {self._uptime_text()}")
                if self.error_count:
                    parts.append(f"日志里出现 {self.error_count} 条错误")
                return "　·　".join(parts) if parts else "客户端正在运行。"
            if state == STATE_STOPPING:
                return "正在结束客户端进程…"
            if state == STATE_STOPPED:
                return "内网穿透已停止，再次启动即可重新连接。"
            if state == STATE_FAILED:
                return "客户端异常退出，请查看终端日志。"
            return ""

        def _uptime_text(self) -> str:
            if not self.started_at:
                return "00:00"
            seconds = int(time.time() - self.started_at)
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            if hours:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"

        def _update_status_detail(self) -> None:
            state = self.process.state()
            self.dashboard.set_state(state, self._detail_text(state))
            self.terminal_page.set_state(state)

        def _update_buttons(self, state: str) -> None:
            running = state in (STATE_STARTING, STATE_RUNNING, STATE_CONNECTED, STATE_STOPPING)
            for start_button in (self.dashboard.start_button, self.terminal_page.start_button):
                start_button.setEnabled(not running)
                ActionButton.set_muted(start_button, running)
            for stop_button in (self.dashboard.stop_button, self.terminal_page.stop_button):
                stop_button.setEnabled(running)
                ActionButton.set_muted(stop_button, not running)

        # -------------------------------------------------------------- 终端交互

        def _on_terminal_input(self, text: str) -> None:
            if not self.process.isRunning():
                self.message("内网穿透还没有启动，无法发送命令。", "log_warning")
                return
            if not self.process.send(text):
                self.message("写入客户端进程失败（进程可能已经退出）。", "log_error")

        def _on_local_command(self, command: str) -> None:
            if command in ("clear", "cls"):
                for terminal in self.terminals():
                    terminal.clear_log()
            elif command == "stop":
                self.stop()
            else:
                self.message("可用命令：clear 清屏 / stop 停止内网穿透 / 其它内容会原样发送给客户端。")

        # -------------------------------------------------------------- 其它

        def _on_mc_confirmed(self, checked: bool) -> None:
            self.config["mc_confirmed"] = bool(checked)
            self._save_config()
            if getattr(self, "_restoring", False):
                return  # 启动时恢复配置，不需要提示
            if checked:
                self.message("已确认《我的世界》局域网世界开启，可以启动内网穿透了。", "log_success")
                self.notify("准备就绪", "现在可以启动内网穿透", "点击「启动内网穿透」")
            else:
                self.message("已取消《我的世界》局域网确认。", "log_warning")

        def _print_banner(self) -> None:
            self.message(f"frp-panel 可视化客户端已就绪，客户端程序：{paths.FRP_EXE.name}", "accent")
            self.message("使用顺序：① 在《我的世界》里开启局域网 → ② 到网页复制启动命令 → "
                         "③ 粘贴并启动内网穿透。", "accent")
            self.message(f"提示：命令开头的 frp-panel 会自动改写成本机的 {paths.FRP_EXE_DISPLAY}", "text_e")
            if not paths.FRP_EXE.exists():
                self.message(f"警告：找不到客户端程序 {paths.FRP_EXE}，请把它放回工作区目录。", "log_error")

        def _on_unhandled_exception(self, text: str) -> None:
            """界面里出现未处理的异常时，把信息写进终端而不是让程序直接崩溃。"""
            try:
                self.message("界面出现未处理的异常（程序会继续运行）：", "log_error")
                for line in text.splitlines():
                    self.message(line, "log_error", prefix="      ")
            except Exception:  # noqa: BLE001
                pass

        def _save_config(self) -> None:
            self.config["panel_url"] = self.dashboard.panel_url()
            self.config["command"] = self.dashboard.command_text()
            self.config["mc_confirmed"] = bool(self.dashboard.mc_confirmed())
            self.config["appearance"] = self.appearance.to_dict()
            size = self.size()
            self.config["window_size"] = [size.width(), size.height()]
            position = self.pos()
            self.config["window_pos"] = [position.x(), position.y()]
            config_module.save(self.config)

        # -------------------------------------------------------------- 生命周期

        def _trace(self, message: str) -> None:
            """开发排查用：设置环境变量 FRP_GUI_TRACE=1 时记录窗口事件。"""
            import os

            if not os.environ.get("FRP_GUI_TRACE"):
                return
            try:
                with open(paths.BASE_DIR / "frp_client_trace.log", "a", encoding="utf-8") as handle:
                    handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
            except OSError:
                pass

        def showEvent(self, event):
            super().showEvent(event)
            self._ever_shown = True
            self._trace(f"showEvent visible={self.isVisible()} minimized={self.isMinimized()}")

        def hideEvent(self, event):
            super().hideEvent(event)
            self._trace("hideEvent")

        def resizeEvent(self, event):
            super().resizeEvent(event)
            guide = getattr(self, "guide", None)
            if guide is not None:
                guide.reposition()

        def keyPressEvent(self, event):
            if event.key() == Qt.Key_Escape and self._on_guide_escape():
                event.accept()
                return
            super().keyPressEvent(event)

        def closeEvent(self, event):
            # 点右上角关闭按钮的行为可以在「外观与设置」页里改：
            # 收进托盘（默认）/ 最小化到任务栏 / 直接退出
            action = str(self.config.get("close_action") or "tray")
            self._trace(f"closeEvent action={action} quitting={self._quitting} tray={self._tray is not None}")

            if not self._quitting:
                if action == "tray" and self._tray is not None:
                    event.ignore()
                    self.hide()
                    self._notify_minimized_to_tray()
                    self._trace("closeEvent -> 已隐藏到托盘")
                    QTimer.singleShot(2500, self._trim)  # 收进托盘后顺手回收内存
                    return

                if action in ("tray", "taskbar"):
                    # 托盘不可用时也走这里：最小化到任务栏，任务栏上一定看得见
                    event.ignore()
                    self.showMinimized()
                    self.message("窗口已最小化到任务栏，点任务栏上的图标就能回来。", "accent")
                    self._trace("closeEvent -> 已最小化到任务栏")
                    return

            try:
                if self.process.state() != STATE_IDLE:
                    self.process.stop()
                self._save_config()
                self._stop_timers()
            except Exception:  # noqa: BLE001 - 关闭窗口时不再抛异常
                pass

            if self._tray is not None:
                self._tray.hide()

            super().closeEvent(event)

            # 托盘不可用时不会有「退出」菜单，这里保证关掉窗口就等于退出程序
            application = QApplication.instance()
            if application is not None:
                application.quit()

        def _stop_timers(self) -> None:
            """退出前把定时器都停掉，免得事件循环结束之后还有回调进来。"""
            for name in ("_wake_timer", "_trim_timer", "_uptime_timer",
                         "_parse_timer", "_appearance_save_timer"):
                timer = getattr(self, name, None)
                if timer is not None:
                    try:
                        timer.stop()
                    except Exception:  # noqa: BLE001
                        pass
            guide = getattr(self, "guide", None)
            if guide is not None:
                try:
                    guide.hide()
                except Exception:  # noqa: BLE001
                    pass

    return FrpPanelClientWindow()
