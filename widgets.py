"""界面里复用的小部件。

这里的控件都实现 ``apply_appearance()``：外观设置一变，
:meth:`frp_client.appearance.Appearance.apply` 就会遍历控件树逐个调用它，
因此颜色、字体、圆角都是「用到时现取」，而不是构造时写死。
"""

from __future__ import annotations

import itertools
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeyEvent, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from frp_client import ansi, appearance
from frp_client.bootstrap import icon
from frp_client.process import (
    STATE_CONNECTED,
    STATE_FAILED,
    STATE_IDLE,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    STATE_STOPPING,
)

_NAME_COUNTER = itertools.count(1)


def unique_name(prefix: str) -> str:
    return f"{prefix}_{next(_NAME_COUNTER)}"


# --------------------------------------------------------------------------- 状态文案

STATUS_STYLE = {
    STATE_IDLE: ("未启动", "text_e"),
    STATE_STARTING: ("正在启动…", "log_warning"),
    STATE_RUNNING: ("运行中", "accent"),
    STATE_CONNECTED: ("已连接，内网穿透已建立", "log_success"),
    STATE_STOPPING: ("正在停止…", "log_warning"),
    STATE_STOPPED: ("已停止", "text_e"),
    STATE_FAILED: ("已停止（进程异常退出）", "log_error"),
}


def status_text(state: str) -> str:
    return STATUS_STYLE.get(state, STATUS_STYLE[STATE_IDLE])[0]


def status_color(state: str) -> str:
    return appearance.color(STATUS_STYLE.get(state, STATUS_STYLE[STATE_IDLE])[1])


# --------------------------------------------------------------------------- 图标 / 字体 / 颜色


def resolve_color(key: str, default: str = "#DFDFDF") -> str:
    """把颜色键解析成色号；如果本身就是色号就原样返回。"""
    if isinstance(key, str) and key.startswith("#"):
        return key
    return appearance.current().palette().get(key, default)


def svg_pixmap(name: str, size: int = 20, color_code: str | None = None) -> QPixmap:
    """把组件库内置图标渲染成 QPixmap。"""
    from siui.core import SiGlobal

    return SiGlobal.siui.iconpack.toPixmap(name, QSize(size, size), color_code)


def make_font(size: int, mono: bool = False, bold: bool = False, scale: bool = True) -> QFont:
    """按外观设置生成字体。"""
    current = appearance.current()
    pal = current.palette()

    families = [pal["mono_family"], "Consolas", "Courier New"] if mono else \
        [pal["font_family"], "Microsoft YaHei UI", "Segoe UI"]

    if scale:
        size = max(8, round(size * float(current.get("font_scale") or 1.0)))

    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(size)
    font.setBold(bold)
    if mono:
        font.setStyleHint(QFont.Monospace)
    return font


class ThemedLabel(QLabel):
    """跟随外观设置的文字标签。

    ``color_key`` 可以传派生色板里的键（如 ``"text_d"``），也可以直接传色号。
    """

    def __init__(self,
                 text: str = "",
                 size: int = 14,
                 color_key: str = "text_b",
                 bold: bool = False,
                 wrap: bool = False,
                 mono: bool = False,
                 parent=None) -> None:
        super().__init__(text, parent)

        self._frp_own_font = True
        self._size = size
        self._color_key = color_key
        self._bold = bold
        self._mono = mono

        self.setWordWrap(wrap)
        if wrap:
            self.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.apply_appearance()

    def setColorKey(self, color_key: str) -> None:
        self._color_key = color_key
        self.apply_appearance()

    def colorKey(self) -> str:
        return self._color_key

    def apply_appearance(self) -> None:
        self.setFont(make_font(self._size, mono=self._mono, bold=self._bold))
        self.setStyleSheet(f"color: {resolve_color(self._color_key)}; background: transparent;")


def text_label(text: str,
               size: int = 14,
               color_code: str = "text_b",
               bold: bool = False,
               parent=None,
               wrap: bool = False) -> ThemedLabel:
    """创建跟随外观的标签（保留旧函数名，方便各页面调用）。"""
    return ThemedLabel(text, size, color_code, bold, wrap, parent=parent)


def mono_label(text: str = "",
               size: int = 13,
               color_code: str = "text_c",
               parent=None) -> ThemedLabel:
    return ThemedLabel(text, size, color_code, mono=True, parent=parent)


class ThemedIconLabel(QLabel):
    """跟随外观色的图标标签。"""

    def __init__(self, name: str, size: int = 20, color_key: str = "text_b", parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self._color_key = color_key
        self.setFixedSize(size, size)
        self.apply_appearance()

    def setName(self, name: str) -> None:
        self._name = name
        self.apply_appearance()

    def apply_appearance(self) -> None:
        self.setPixmap(svg_pixmap(self._name, self._size, resolve_color(self._color_key)))
        self.setStyleSheet("background: transparent;")


def icon_label(name: str, size: int = 20, color_code: str = "text_b", parent=None) -> ThemedIconLabel:
    return ThemedIconLabel(name, size, color_code, parent)


# --------------------------------------------------------------------------- 基础输入控件


class ThemedLineEdit(QLineEdit):
    """跟随外观的输入框。"""

    def __init__(self, text: str = "", parent=None, mono: bool = False) -> None:
        super().__init__(text, parent)
        self._frp_own_font = True
        self._mono = mono
        self.setMinimumHeight(36)
        self.apply_appearance()

    def apply_appearance(self) -> None:
        pal = appearance.current().palette()
        size = int(appearance.current().get("terminal_font_size") or 13) if self._mono else 14
        self.setFont(make_font(size, mono=self._mono, scale=not self._mono))
        self.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {pal['input_bg']};"
            f"  color: {pal['text_b']};"
            f"  border: 1px solid {pal['border']};"
            f"  border-radius: {pal['radius_input']}px;"
            f"  padding: 7px 10px;"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {pal['accent']}; }}"
        )


class ThemedCheckBox(QCheckBox):
    """跟随外观的复选框。"""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._frp_own_font = True
        self.apply_appearance()

    def apply_appearance(self) -> None:
        pal = appearance.current().palette()
        self.setFont(make_font(14))
        self.setStyleSheet(
            f"QCheckBox {{ color: {pal['text_d']}; background: transparent; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px;"
            f"  border: 1px solid {pal['border']}; border-radius: 4px;"
            f"  background-color: {pal['input_bg']}; }}"
            f"QCheckBox::indicator:checked {{ background-color: {pal['accent']};"
            f"  border: 1px solid {pal['accent']}; }}"
        )


class ThemedToolButton(QPushButton):
    """工具栏按钮、发送按钮这类小按钮。"""

    def __init__(self, text: str, parent=None, role: str = "ghost", height: int = 26) -> None:
        super().__init__(text, parent)
        self._frp_own_font = True
        self._role = role
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(height)
        self.apply_appearance()

    def apply_appearance(self) -> None:
        pal = appearance.current().palette()
        radius = max(2, int(pal["radius_button"]) - 2)
        self.setFont(make_font(13))

        if self._role == "primary":
            self.setStyleSheet(
                f"QPushButton {{ background-color: {pal['accent_bg']}; color: {pal['accent_text']};"
                f"  border: none; border-radius: {radius}px; padding: 7px 0px; }}"
                f"QPushButton:hover {{ background-color: {pal['accent']}; }}"
                f"QPushButton:pressed {{ background-color: {pal['accent']}; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {pal['text_d']};"
                f"  border: 1px solid {pal['border']}; border-radius: {radius}px;"
                f"  padding: 4px 10px; }}"
                f"QPushButton:hover {{ color: {pal['text_b']}; border: 1px solid {pal['bg_e']}; }}"
                f"QPushButton:pressed {{ background-color: {pal['hover_bg']}; }}"
            )


class ThemedSlider(QSlider):
    """跟随外观的滑块。"""

    def __init__(self, orientation=Qt.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setMinimumHeight(24)
        self.apply_appearance()

    def apply_appearance(self) -> None:
        pal = appearance.current().palette()
        self.setStyleSheet(
            f"QSlider {{ background: transparent; }}"
            f"QSlider::groove:horizontal {{ height: 6px; background: {pal['input_bg']};"
            f"  border-radius: 3px; }}"
            f"QSlider::sub-page:horizontal {{ background: {pal['accent']}; border-radius: 3px; }}"
            f"QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0;"
            f"  border-radius: 7px; background: {pal['accent']}; }}"
        )


class ThemedComboBox(QWidget):
    """跟随外观的下拉框。"""

    def __init__(self, items: list[str] | None = None, parent=None) -> None:
        from PyQt5.QtWidgets import QComboBox

        super().__init__(parent)
        self._frp_own_font = True
        self._handler = None

        self.combo = QComboBox(self)
        if items:
            self.combo.addItems(items)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)

        self.combo.currentTextChanged.connect(self._on_changed)
        self.apply_appearance()

    def _on_changed(self, text: str) -> None:
        if self._handler is not None:
            self._handler(text)

    def onChanged(self, handler) -> None:
        self._handler = handler

    def currentText(self) -> str:
        return self.combo.currentText()

    def setCurrentText(self, text: str) -> None:
        self.combo.setCurrentText(text)

    def combo_qss(self) -> str:
        pal = appearance.current().palette()
        return (
            f"QComboBox {{ background-color: {pal['input_bg']}; color: {pal['text_b']};"
            f"  border: 1px solid {pal['border']}; border-radius: {pal['radius_input']}px;"
            f"  padding: 6px 10px; }}"
            f"QComboBox:hover {{ border: 1px solid {pal['accent']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {pal['card_bg']};"
            f"  color: {pal['text_b']}; border: 1px solid {pal['border']};"
            f"  selection-background-color: {pal['hover_bg']}; outline: none; }}"
        )

    def apply_appearance(self) -> None:
        self.combo.setFont(make_font(14))
        self.combo.setMinimumHeight(36)
        self.combo.setStyleSheet(self.combo_qss())


class ThemedFontComboBox(ThemedComboBox):
    """字体选择框。"""

    def __init__(self, parent=None) -> None:
        from PyQt5.QtWidgets import QFontComboBox

        super().__init__(None, parent)

        layout = self.layout()
        layout.removeWidget(self.combo)
        self.combo.deleteLater()

        self.combo = QFontComboBox(self)
        self.combo.currentTextChanged.connect(self._on_changed)
        layout.addWidget(self.combo)
        self.apply_appearance()


class ColorSwatchButton(QPushButton):
    """色块按钮：显示当前颜色，点击打开取色器。"""

    colorChanged = pyqtSignal(str)

    def __init__(self, color_code: str = "#FFFFFF", parent=None, width: int = 96, height: int = 30) -> None:
        super().__init__(parent)
        self._frp_own_font = True
        self._color_code = color_code
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(width, height)
        self.clicked.connect(self._pick_color)
        self.apply_appearance()

    def color(self) -> str:
        return self._color_code

    def setColor(self, color_code: str) -> None:
        self._color_code = color_code
        self.apply_appearance()

    def _pick_color(self) -> None:
        from PyQt5.QtGui import QColor

        chosen = QColorDialog.getColor(QColor(self._color_code), self, "选择颜色")
        if chosen.isValid():
            self.setColor(chosen.name().upper())
            self.colorChanged.emit(self._color_code)

    def apply_appearance(self) -> None:
        from PyQt5.QtGui import QColor

        pal = appearance.current().palette()
        text_color = "#FFFFFF" if QColor(self._color_code).lightness() < 150 else "#1C191F"
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color_code}; color: {text_color};"
            f"  border: 1px solid {pal['border']}; border-radius: 6px;"
            f"  font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ border: 1px solid {pal['accent']}; }}"
        )
        self.setText(self._color_code.upper().lstrip("#"))


# --------------------------------------------------------------------------- 卡片


class Card(QWidget):
    """圆角卡片容器，内部使用纵向布局。"""

    def __init__(self, parent=None, title: str = "", icon_name: str | None = None,
                 subtitle: str = "", spacing: int = 10) -> None:
        super().__init__(parent)

        self._qss_name = unique_name("frpCard")
        self.setObjectName(self._qss_name)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 18)
        self._layout.setSpacing(spacing)

        if title or icon_name:
            header = QWidget(self)
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(10)

            if icon_name:
                header_layout.addWidget(ThemedIconLabel(icon_name, 20, "text_b", header))

            if title:
                header_layout.addWidget(text_label(title, 16, "text_a", bold=True, parent=header))

            if subtitle:
                header_layout.addWidget(text_label(subtitle, 13, "text_e", parent=header))

            header_layout.addStretch(1)
            self._layout.addWidget(header)

        self.apply_appearance()

    def layout(self) -> QVBoxLayout:
        return self._layout

    def addWidget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def addLayout(self, layout) -> None:
        self._layout.addLayout(layout)

    def addStretch(self, stretch: int = 1) -> None:
        self._layout.addStretch(stretch)

    def apply_appearance(self) -> None:
        pal = appearance.current().palette()
        self.setStyleSheet(
            f"#{self._qss_name} {{"
            f"  background-color: {pal['card_bg']};"
            f"  border: 1px solid {pal['border']};"
            f"  border-radius: {pal['radius_card']}px;"
            f"}}"
        )


# --------------------------------------------------------------------------- 状态灯


class StatusPill(QWidget):
    """状态指示灯：小圆点 + 文字。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.dot = QLabel(self)
        self.dot.setFixedSize(10, 10)
        layout.addWidget(self.dot, 0, Qt.AlignVCenter)

        self.text = text_label("未启动", 14, "text_c", parent=self)
        layout.addWidget(self.text, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        self._state = STATE_IDLE
        self.apply_appearance()

    def setState(self, state: str) -> None:
        self._state = state
        self.apply_appearance()

    def state(self) -> str:
        return self._state

    def apply_appearance(self) -> None:
        color = status_color(self._state)
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        self.text.setText(status_text(self._state))
        self.text.setColorKey(color)


# --------------------------------------------------------------------------- 按钮


class ActionButton:
    """基于组件库重构版按钮的工厂：统一主 / 次 / 危险 / 幽灵四种外观。"""

    # 每种按钮在派生色板里对应的（底色 / 文字色 / 图标色）
    ROLES = {
        "primary": ("accent_bg", "accent_text", "accent_text"),
        "secondary": ("button_bg", "button_text", "text_b"),
        "danger": ("danger_bg", "danger_text", "danger_text"),
        "ghost": (None, "ghost_text", "text_d"),
    }

    @staticmethod
    def create(text: str,
               parent=None,
               kind: str = "secondary",
               icon_name: str | None = None,
               height: int = 40,
               width: int | None = None,
               tooltip: str = "") -> QPushButton:
        from siui.components.button import SiFlatButton, SiPushButtonRefactor

        button = SiFlatButton(parent) if kind == "ghost" else SiPushButtonRefactor(parent)
        button.setText(text)
        button.setFixedHeight(height)
        if width is not None:
            button.setFixedWidth(width)
        if tooltip:
            button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)

        button._frp_kind = kind
        button._frp_icon_name = icon_name
        button._frp_muted = False

        # 挂上 apply_appearance，外观刷新时会被控件树遍历自动调用
        def apply_appearance() -> None:
            ActionButton.style_button(button,
                                      getattr(button, "_frp_kind", kind),
                                      getattr(button, "_frp_muted", False))

        button.apply_appearance = apply_appearance
        apply_appearance()
        return button

    @staticmethod
    def style_button(button, kind: str, muted: bool = False) -> None:
        from PyQt5.QtGui import QColor

        pal = appearance.current().palette()
        radius = int(pal["radius_button"])

        if muted:
            body_color = pal["muted_bg"]
            text_color = pal["muted_text"]
            icon_color = pal["muted_text"]
            background_color = "#00000000"
        else:
            body_key, text_key, icon_key = ActionButton.ROLES.get(kind, ActionButton.ROLES["secondary"])
            body_color = pal[body_key] if body_key else "#00000000"
            text_color = pal[text_key]
            icon_color = pal[icon_key]
            background_color = body_color if kind == "primary" else "#00000000"

        style = button.style_data
        style.button_color = QColor(body_color)
        style.text_color = QColor(text_color)
        style.background_color = QColor(background_color)
        style.hover_color = QColor(pal["accent_hover"])
        style.click_color = QColor(pal["accent_press"])
        style.border_radius = radius
        style.border_inner_radius = max(1, radius - 3)

        icon_name = getattr(button, "_frp_icon_name", None)
        if icon_name:
            button.setSvgIcon(icon(icon_name, icon_color))
        button.update()

    @staticmethod
    def set_muted(button, muted: bool) -> None:
        """让按钮看起来是「不可用」的淡色状态。"""
        if getattr(button, "_frp_kind", None) is None:
            return
        button._frp_muted = bool(muted)
        ActionButton.style_button(button, button._frp_kind, muted)


# --------------------------------------------------------------------------- 终端


class AnsiLogView(QPlainTextEdit):
    """只读的彩色日志视图。"""

    MAX_BLOCKS = 1200  # 只保留最近这些行日志，够排查问题又不会一直涨内存

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._frp_own_font = True

        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFrameStyle(0)
        self.setPlaceholderText("这里会实时显示内网穿透客户端的输出…")

        self.auto_scroll = True
        self.apply_appearance()

    def apply_appearance(self) -> None:
        current = appearance.current()
        pal = current.palette()

        font = QFont()
        font.setFamilies([pal["mono_family"], "Consolas", "JetBrains Mono", "Courier New"])
        font.setPixelSize(max(8, int(current.get("terminal_font_size") or 13)))
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)

        self.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {pal['terminal_bg']};"
            f"  color: {pal['terminal_text']};"
            f"  border: 1px solid {pal['border']};"
            f"  border-radius: {pal['radius_input']}px;"
            f"  padding: 8px;"
            f"  selection-background-color: {pal['terminal_selection']};"
            f"}}"
        )

    def append_raw(self, line: str) -> None:
        html_line = ansi.ansi_to_html(line)
        if html_line:
            self.appendHtml(html_line)
        else:
            self.appendPlainText("")
        self._scroll_if_needed()

    def append_message(self, text: str, color_code: str = "log_system", prefix: str = "[GUI]") -> None:
        self.appendHtml(ansi.plain_message_html(text, resolve_color(color_code), prefix))
        self._scroll_if_needed()

    def _scroll_if_needed(self) -> None:
        if self.auto_scroll:
            scrollbar = self.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def toPlainTextAll(self) -> str:
        return self.toPlainText()


class TerminalWidget(QWidget):
    """内置终端：日志视图 + 命令输入框。

    信号:
        - inputSubmitted(str): 用户在输入框里回车/点击发送
        - localCommand(str):   需要宿主程序处理的本地命令（clear / stop / help）
    """

    inputSubmitted = pyqtSignal(str)
    localCommand = pyqtSignal(str)

    LOCAL_COMMANDS = {"clear", "cls", "help", "?", "stop"}

    def __init__(self,
                 parent=None,
                 title: str = "内置终端",
                 show_input: bool = True,
                 compact: bool = False) -> None:
        super().__init__(parent)

        self._history: list[str] = []
        self._history_index = 0
        self._layout_dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- 工具栏
        toolbar = QWidget(self)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        if title:
            toolbar_layout.addWidget(text_label(title, 14, "text_d", bold=True, parent=toolbar))
        toolbar_layout.addStretch(1)

        self.auto_scroll_box = ThemedCheckBox("自动滚动", toolbar)
        self.auto_scroll_box.setChecked(True)
        self.auto_scroll_box.toggled.connect(self._on_auto_scroll_toggled)
        toolbar_layout.addWidget(self.auto_scroll_box)

        self._clear_button = ThemedToolButton("清空", toolbar)
        self._clear_button.clicked.connect(self.clear_log)
        toolbar_layout.addWidget(self._clear_button)

        self._copy_button = ThemedToolButton("复制", toolbar)
        self._copy_button.clicked.connect(self.copy_all)
        toolbar_layout.addWidget(self._copy_button)

        self._save_button = ThemedToolButton("保存日志", toolbar)
        self._save_button.clicked.connect(self.save_log)
        toolbar_layout.addWidget(self._save_button)

        layout.addWidget(toolbar)

        # ---- 日志视图
        self.log_view = AnsiLogView(self)
        layout.addWidget(self.log_view, 1)

        # ---- 输入行
        self.input_edit: ThemedLineEdit | None = None
        self._prompt = None
        self._send_button: ThemedToolButton | None = None
        self._hint = None

        if show_input:
            input_row = QWidget(self)
            input_layout = QHBoxLayout(input_row)
            input_layout.setContentsMargins(0, 0, 0, 0)
            input_layout.setSpacing(8)

            self._prompt = text_label("❯", 15, "accent", bold=True, parent=input_row)
            self._prompt.setFixedWidth(14)
            input_layout.addWidget(self._prompt)

            self.input_edit = ThemedLineEdit(parent=input_row, mono=True)
            self.input_edit.setPlaceholderText("输入命令后回车发送给客户端（例如：help / clear）")
            self.input_edit.returnPressed.connect(self._on_input_submitted)
            self.input_edit.installEventFilter(self)
            input_layout.addWidget(self.input_edit, 1)

            self._send_button = ThemedToolButton("发送", input_row, role="primary", height=34)
            self._send_button.setFixedWidth(72)
            self._send_button.clicked.connect(self._on_input_submitted)
            input_layout.addWidget(self._send_button)

            layout.addWidget(input_row)

            if not compact:
                self._hint = text_label(
                    "提示：终端里的 clear 可以清屏，stop 可以让本工具停止内网穿透。",
                    12, "text_e", parent=self)
                layout.addWidget(self._hint)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    # ------------------------------------------------------------ 外观

    def apply_appearance(self) -> None:
        for widget in (self._clear_button, self._copy_button, self._save_button,
                       self._send_button, self.input_edit, self.auto_scroll_box,
                       self._prompt, self._hint):
            applier = getattr(widget, "apply_appearance", None)
            if callable(applier):
                applier()

    # ------------------------------------------------------------ 终端行为

    def eventFilter(self, obj, event):
        if obj is self.input_edit and isinstance(event, QKeyEvent) and event.type() == QKeyEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self._recall_history(-1)
                return True
            if event.key() == Qt.Key_Down:
                self._recall_history(1)
                return True
        return super().eventFilter(obj, event)

    def _recall_history(self, step: int) -> None:
        if not self._history or self.input_edit is None:
            return
        self._history_index = max(0, min(len(self._history), self._history_index + step))
        if self._history_index >= len(self._history):
            self.input_edit.setText("")
        else:
            self.input_edit.setText(self._history[self._history_index])

    def _on_input_submitted(self) -> None:
        if self.input_edit is None:
            return
        text = self.input_edit.text().strip()
        self.input_edit.clear()
        if not text:
            return

        self._history.append(text)
        self._history_index = len(self._history)

        lowered = text.lower()
        if lowered in self.LOCAL_COMMANDS:
            self.append_message(f"❯ {text}", "text_d", prefix="")
            self.localCommand.emit(lowered)
            return

        self.append_message(f"❯ {text}", "accent", prefix="")
        self.inputSubmitted.emit(text)

    def _on_auto_scroll_toggled(self, checked: bool) -> None:
        self.log_view.auto_scroll = checked
        if checked:
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------ 对外接口

    def append_raw(self, line: str) -> None:
        self.log_view.append_raw(line)
        if not self.log_view.isVisible():
            self._layout_dirty = True

    def append_message(self, text: str, color_code: str = "log_system", prefix: str = "[GUI]") -> None:
        self.log_view.append_message(text, color_code, prefix)
        if not self.log_view.isVisible():
            self._layout_dirty = True

    def refresh(self) -> None:
        """页面从隐藏变为可见时调用：让日志重新排版并滚到最新一行。

        QPlainTextEdit 在隐藏状态下追加内容时不会完整排版，刚切到该页面时
        只会显示最后一行。补一个空行可以强制它重新排版整篇文档。
        """
        from PyQt5.QtGui import QTextCursor

        view = self.log_view
        if self._layout_dirty:
            view.appendHtml("")
            self._layout_dirty = False
        if view.auto_scroll:
            cursor = view.textCursor()
            cursor.movePosition(QTextCursor.End)
            view.setTextCursor(cursor)
            scrollbar = view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        view.viewport().update()

    def clear_log(self) -> None:
        self.log_view.clear()

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainTextAll())
        self.append_message("日志已复制到剪贴板。", "log_success")

    def save_log(self) -> None:
        from datetime import datetime

        default_name = f"frp-panel-{datetime.now():%Y%m%d-%H%M%S}.log"
        path, _ = QFileDialog.getSaveFileName(self, "保存终端日志", default_name,
                                              "日志文件 (*.log);;文本文件 (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.log_view.toPlainTextAll(), encoding="utf-8")
        except OSError as error:
            self.append_message(f"保存失败：{error}", "log_error")
            return
        self.append_message(f"日志已保存到 {path}", "log_success")
