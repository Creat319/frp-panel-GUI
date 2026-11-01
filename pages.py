"""页面：启动面板、内置终端、使用帮助。

（外观设置页在 :mod:`frp_client.page_appearance` 里。）

所有颜色都通过颜色键在绘制时取用，页面本身实现了 ``apply_appearance()``
来刷新那些「随状态变化」的样式（例如命令预览成功 / 失败的不同配色）。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from siui.components.page import SiPage

from frp_client import appearance, paths
from frp_client.widgets import (
    ActionButton,
    Card,
    StatusPill,
    TerminalWidget,
    ThemedLabel,
    ThemedLineEdit,
    mono_label,
    resolve_color,
    text_label,
)


def bullet_lines(lines: list[str], size: int = 13, color_code: str = "text_c", parent=None) -> QWidget:
    """把若干行文字做成一个纵向排列的小部件。"""
    holder = QWidget(parent)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for line in lines:
        label = text_label(line, size, color_code, parent=holder, wrap=True)
        label.setMinimumHeight(20)
        layout.addWidget(label)
    return holder


class PreviewLabel(ThemedLabel):
    """命令预览：等宽字体 + 终端底色 + 圆角。"""

    def __init__(self, parent=None) -> None:
        super().__init__("", 12, "text_c", mono=True, parent=parent)
        self.setWordWrap(True)
        self.setFixedHeight(64)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.apply_appearance()

    def apply_appearance(self) -> None:
        super().apply_appearance()
        pal = appearance.current().palette()
        self.setStyleSheet(
            f"color: {resolve_color(self.colorKey())};"
            f"background-color: {pal['terminal_bg']};"
            f"border-radius: {pal['radius_input']}px;"
            f"padding: 8px;"
        )


class ContentPage(SiPage):
    """把 SiPage 的滚动内容换成一个使用 Qt 布局的容器，方便自由排版。"""

    def __init__(self,
                 parent=None,
                 title: str = "",
                 padding: int = 48,
                 max_width: int = 1084,
                 fill_height: bool = False,
                 spacing: int = 16) -> None:
        super().__init__(parent)

        self.setPadding(padding)
        self.setScrollMaximumWidth(max_width)
        if title:
            self.setTitle(title)

        self.content = QWidget(self)
        self.content.resize(max_width, 600)

        self.vbox = QVBoxLayout(self.content)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(spacing)

        self.setAttachment(self.content)

        self._fill_height = fill_height
        self._padding = padding
        self._max_width = max_width

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(320, min(event.size().width() - self._padding * 2, self._max_width))
        available = max(100, self.scroll_area.height())
        natural = self.vbox.sizeHint().height()
        height = available if self._fill_height else max(natural, available)
        self.content.setFixedSize(width, height)

    def showEvent(self, event):
        super().showEvent(event)
        # 页面从隐藏变为可见时，让内置终端重新排版并滚到最新一行
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            terminal.refresh()


# =========================================================================== 启动面板


class DashboardPage(ContentPage):
    """主页：三步引导 + 状态 + 实时输出。"""

    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    openPanelRequested = pyqtSignal(str)
    commandEdited = pyqtSignal(str)
    pasteRequested = pyqtSignal()
    mcConfirmedChanged = pyqtSignal(bool)

    LEFT_WIDTH = 596

    def __init__(self, parent, panel_url: str = paths.DEFAULT_PANEL_URL):
        super().__init__(parent, title="内网穿透 · 启动面板", padding=44, max_width=1240, spacing=16)
        vbox = self.vbox

        self._preview_state: tuple[str | None, str, str | None] = (None, "", None)

        columns = QWidget(self.content)
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)

        left = QWidget(columns)
        left.setFixedWidth(self.LEFT_WIDTH)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        left_layout.addWidget(self._build_step1(panel_url))
        left_layout.addWidget(self._build_step2())
        left_layout.addWidget(self._build_step3())
        left_layout.addStretch(1)

        right = QWidget(columns)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        right_layout.addWidget(self._build_status_card())

        self.terminal_card = Card(self, title="实时输出", icon_name="ic_fluent_window_dev_tools_regular")
        self.terminal = TerminalWidget(self.terminal_card, title="", show_input=True, compact=True)
        self.terminal.log_view.setMinimumHeight(220)
        self.terminal_card.addWidget(self.terminal, 1)
        self.terminal_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_layout.addWidget(self.terminal_card, 1)

        columns_layout.addWidget(left, 0)
        columns_layout.addWidget(right, 1)
        vbox.addWidget(columns, 1)

    # ------------------------------------------------------------ 步骤卡片

    def _build_step1(self, panel_url: str) -> Card:
        card = Card(self, title="第 1 步 · 在网页上获取启动命令", icon_name="ic_fluent_globe_regular")

        card.addWidget(text_label(
            "登录 frp-panel 面板 → 打开「客户端」页面 → 复制你的客户端启动命令。",
            13, "text_d", parent=card, wrap=True))

        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self.panel_url_edit = ThemedLineEdit(panel_url, row)
        row_layout.addWidget(self.panel_url_edit, 1)

        open_button = ActionButton.create(
            "打开网页", row, kind="secondary", icon_name="ic_fluent_open_regular", height=36, width=110)
        open_button.clicked.connect(lambda: self.openPanelRequested.emit(self.panel_url_edit.text().strip()))
        row_layout.addWidget(open_button)

        card.addWidget(row)
        return card

    def _build_step2(self) -> Card:
        card = Card(self, title="第 2 步 · 把启动命令粘贴到这里", icon_name="ic_fluent_clipboard_paste_regular")

        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        from siui.components.widgets import SiLineEdit

        self.command_edit = SiLineEdit(row)
        self.command_edit.setFixedHeight(40)
        self.command_edit.lineEdit().setPlaceholderText(
            "frp-panel client -s xxxxxxxx-xxxx -i your.client.id --api-url http://… --rpc-url grpc://…")
        self.command_edit.lineEdit().textChanged.connect(self.commandEdited.emit)
        row_layout.addWidget(self.command_edit, 1)

        paste_button = ActionButton.create(
            "粘贴", row, kind="secondary", icon_name="ic_fluent_clipboard_paste_regular", height=40, width=92)
        paste_button.clicked.connect(self.pasteRequested.emit)
        row_layout.addWidget(paste_button)

        clear_button = ActionButton.create(
            "清空", row, kind="ghost", icon_name="ic_fluent_delete_regular", height=40, width=88)
        clear_button.clicked.connect(lambda: self.command_edit.lineEdit().setText(""))
        row_layout.addWidget(clear_button)

        card.addWidget(row)

        card.addWidget(text_label("将要执行的命令：", 12, "text_e", parent=card))
        self.preview_label = PreviewLabel(card)
        self.preview_label.setText("等待粘贴启动命令…")
        card.addWidget(self.preview_label)

        self.hint_label = text_label("", 12, "log_error", parent=card, wrap=True)
        self.hint_label.setMinimumHeight(20)
        card.addWidget(self.hint_label)

        self.summary_label = text_label("", 12, "text_d", parent=card)
        self.summary_label.setMinimumHeight(20)
        card.addWidget(self.summary_label)
        return card

    def _build_step3(self) -> Card:
        card = Card(self, title="第 3 步 · 先在《我的世界》里开启局域网", icon_name="ic_fluent_people_regular")

        from siui.components.widgets import SiCheckBox

        self.mc_checkbox = SiCheckBox(card)
        self.mc_checkbox.setText("我已经在《我的世界》中开启了对局域网开放的世界")
        self.mc_checkbox.setFixedSize(self.LEFT_WIDTH - 44, 24)
        self.mc_checkbox.toggled.connect(self.mcConfirmedChanged.emit)
        card.addWidget(self.mc_checkbox)

        card.addWidget(text_label(
            "单人游戏 → 进入世界 → ESC →「对局域网开放」，记下端口号。",
            12, "text_d", parent=card, wrap=True))
        card.addWidget(text_label(
            "顺序很重要：先开局域网，再启动内网穿透，朋友才能连进来。",
            12, "log_warning", parent=card, wrap=True))
        card.addWidget(text_label(
            "然后把这台电脑的隧道公网地址发给朋友，他在「多人游戏 → 直接连接」里输入即可加入。",
            12, "text_d", parent=card, wrap=True))
        return card

    def _build_status_card(self) -> Card:
        card = Card(self, title="内网穿透状态", icon_name="ic_fluent_plug_connected_regular")

        self.status_pill = StatusPill(card)
        card.addWidget(self.status_pill)

        self.status_detail = text_label("还没有启动内网穿透。", 12, "text_e", parent=card)
        self.status_detail.setMinimumHeight(20)
        card.addWidget(self.status_detail)

        buttons = QWidget(card)
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        self.start_button = ActionButton.create(
            "启动内网穿透", buttons, kind="primary", icon_name="ic_fluent_play_regular", height=44)
        self.start_button.clicked.connect(self.startRequested.emit)
        buttons_layout.addWidget(self.start_button, 2)

        self.stop_button = ActionButton.create(
            "停止", buttons, kind="danger", icon_name="ic_fluent_stop_regular", height=44, width=110)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        buttons_layout.addWidget(self.stop_button, 1)

        card.addWidget(buttons)
        return card

    # ------------------------------------------------------------ 对外接口

    def apply_appearance(self) -> None:
        # 预览区的配色是随解析状态变的，换肤后按当前状态重新刷一次
        display, summary, error = self._preview_state
        self.show_parse_result(display, summary, error)

    def panel_url(self) -> str:
        return self.panel_url_edit.text().strip()

    def set_panel_url(self, url: str) -> None:
        self.panel_url_edit.setText(url)

    def command_text(self) -> str:
        return self.command_edit.lineEdit().text()

    def set_command_text(self, text: str) -> None:
        self.command_edit.lineEdit().setText(text)
        # 让输入框停在命令开头，方便用户确认程序名已被改写
        self.command_edit.lineEdit().setCursorPosition(0)
        self.command_edit.lineEdit().deselect()

    def mc_confirmed(self) -> bool:
        return bool(self.mc_checkbox.isChecked())

    def show_parse_result(self, display: str | None, summary: str = "", error: str | None = None) -> None:
        self._preview_state = (display, summary, error)

        if error:
            self.preview_label.setText("命令无法识别")
            self.preview_label.setColorKey("log_error")
            self.hint_label.setText(f"⚠ {error}")
            self.hint_label.setColorKey("log_error")
            self.summary_label.setText("")
            return

        if display:
            self.preview_label.setText(display)
            self.preview_label.setColorKey("log_success")
            self.hint_label.setText("✓ 命令已就绪，可以启动内网穿透了。")
            self.hint_label.setColorKey("log_success")
            self.summary_label.setText(summary)
        else:
            self.preview_label.setText("等待粘贴启动命令…")
            self.preview_label.setColorKey("text_e")
            self.hint_label.setText("")
            self.summary_label.setText("")

    def set_state(self, state: str, detail: str = "") -> None:
        self.status_pill.setState(state)
        self.status_detail.setText(detail)


# =========================================================================== 终端页


class TerminalPage(ContentPage):
    """整屏的内置终端。"""

    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent, title="内置终端", padding=44, max_width=4000,
                         fill_height=True, spacing=14)
        vbox = self.vbox

        header = Card(self, title="", spacing=0)
        header.layout().setContentsMargins(20, 14, 20, 14)
        header_row = QWidget(header)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.status_pill = StatusPill(header_row)
        self.status_pill.setFixedWidth(260)
        header_layout.addWidget(self.status_pill)
        header_layout.addStretch(1)

        self.start_button = ActionButton.create(
            "启动内网穿透", header_row, kind="primary", icon_name="ic_fluent_play_regular", height=38, width=170)
        self.start_button.clicked.connect(self.startRequested.emit)
        header_layout.addWidget(self.start_button)

        self.stop_button = ActionButton.create(
            "停止", header_row, kind="danger", icon_name="ic_fluent_stop_regular", height=38, width=110)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        header_layout.addWidget(self.stop_button)

        header.addWidget(header_row)
        vbox.addWidget(header)

        terminal_card = Card(self, title="", spacing=0)
        terminal_card.layout().setContentsMargins(20, 16, 20, 18)
        self.terminal = TerminalWidget(terminal_card, title="frp-panel 客户端输出", show_input=True, compact=False)
        terminal_card.addWidget(self.terminal, 1)
        terminal_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        vbox.addWidget(terminal_card, 1)

    def set_state(self, state: str, detail: str = "") -> None:
        self.status_pill.setState(state)


# =========================================================================== 帮助页


class HelpPage(ContentPage):
    startGuideRequested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent, title="使用帮助", padding=44, max_width=980, spacing=16)
        vbox = self.vbox

        guide_card = Card(self, title="新手引导", icon_name="ic_fluent_book_question_mark_regular")
        guide_card.addWidget(text_label(
            "第一次用？跟着引导走一遍就会了：每一步都会把说明一个字一个字打出来，"
            "看完点「下一步」，随时可以点「跳过引导」。",
            13, "text_d", parent=guide_card, wrap=True))
        guide_row = QWidget(guide_card)
        guide_layout = QHBoxLayout(guide_row)
        guide_layout.setContentsMargins(0, 0, 0, 0)
        guide_layout.setSpacing(10)
        self.guide_button = ActionButton.create(
            "重新播放新手引导", guide_row, kind="primary",
            icon_name="ic_fluent_play_regular", height=38, width=180)
        self.guide_button.clicked.connect(self.startGuideRequested.emit)
        guide_layout.addWidget(self.guide_button)
        guide_layout.addStretch(1)
        guide_card.addWidget(guide_row)
        vbox.addWidget(guide_card)

        vbox.addWidget(self._card(
            "完整使用流程", "ic_fluent_book_question_mark_regular",
            [
                "1. 先在《我的世界》里进入世界，按 ESC → 「对局域网开放」，记下端口号（默认 25565）。",
                "2. 打开 frp-panel 面板网页的「客户端」页面，复制你的启动命令。",
                "3. 回到本程序，把命令粘贴到第 2 步的输入框，程序会自动把开头的 frp-panel 改写成本机的 "
                f"{paths.FRP_EXE_NAME}。",
                "4. 勾选第 3 步的确认框，点击「启动内网穿透」。",
                "5. 在右侧（或「内置终端」页面）看到客户端连上 master 后，把面板里这条隧道的公网地址发给朋友。",
                "6. 朋友用「多人游戏 → 直接连接」输入该地址即可进服。",
                "7. 想调整配色 / 字体 / 圆角，去「外观设置」页面；设置会保存在配置文件里。",
            ]))

        vbox.addWidget(self._card(
            "常见问题", "ic_fluent_question_circle_regular",
            [
                "· 提示 record not found：命令里的客户端 ID / 密钥已失效，请回网页重新复制启动命令。",
                "· 一直重连：确认面板地址能访问、电脑能联网；公司或校园网可能会拦截出站连接。",
                "· 端口被占用：先点「停止」，确认旧进程结束后再启动；也可以重新开局域网换一个端口。",
                "· 点窗口右上角的 × 不会退出程序，而是最小化到系统托盘继续在后台运行；"
                "右键托盘图标可以「结束穿透」或「退出」。",
                "· 关闭之后想回来：再双击一次程序图标，程序会把已经在跑的那个窗口叫到最前面；"
                "也可以点右下角托盘里的小图标（Windows 11 可能把它折叠进了「显示隐藏的图标」）。",
                "· 托盘里实在找不到图标：去「外观与设置 → 窗口与托盘」，"
                "把「关闭窗口时」改成「最小化到任务栏」，任务栏上一定看得见。",
                "· 万一旧程序卡住、窗口怎么都叫不出来，第二次启动会问你要不要"
                "「结束旧程序并重新启动」，点一下就能重启。",
                "· 从托盘菜单「退出」会自动结束内网穿透进程，朋友会掉线。",
                "· 朋友的端口和你的局域网端口不一致时，需要在面板里把隧道的本地端口改成聊天栏提示的那个端口。",
            ]))

        vbox.addWidget(self._card(
            "关于本程序", "ic_fluent_info_regular",
            [
                f"· 客户端程序：{paths.display_path(paths.FRP_EXE)}（与本程序放在同一个目录）",
                f"· 配置文件（含外观设置）：{paths.display_path(paths.CONFIG_FILE)}",
                "· 界面基于 PyQt5 与 PyQt-SiliconUI 组件库构建。",
                "· 终端里的输出就是 frp-panel 客户端的原始日志，可以复制或保存成文件反馈问题。",
                "· 程序收进托盘挂后台时会自动把闲置内存换出（任务管理器里只显示几 MB），"
                "回到前台会自动换回来。",
                "· 想再看一遍新手引导：点上面的「重新播放新手引导」。",
            ]))
        vbox.addStretch(1)

    def _card(self, title: str, icon_name: str, lines: list[str]) -> Card:
        card = Card(self, title=title, icon_name=icon_name)
        card.addWidget(bullet_lines(lines, 13, "text_c", card))
        return card
