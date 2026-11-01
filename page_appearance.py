"""外观设置页。

组件库的外观基本都能在这里调：深色 / 亮色方案、强调色、各级背景与文字色、
图标色、字体与字号、界面缩放、按钮 / 卡片圆角、终端与日志配色、界面动画。

页面只负责读写 :mod:`frp_client.appearance` 里的设置项（会自动写进配置文件），
真正的换肤由主窗口统一调用 ``Appearance.apply()`` 完成 —— 它会遍历控件树
调用每个控件的 ``apply_appearance()``。

要新增一个外观项，只要三步：

1. 在 ``appearance.DARK_DEFAULTS`` / ``LIGHT_DEFAULTS`` 里加一个键；
2. 在需要它的控件 ``apply_appearance()`` 里读这个键；
3. 在本页加一行对应的控件（``_swatch_row`` / ``_slider_row`` / ``_choice_row``）。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from frp_client import appearance
from frp_client.pages import ContentPage
from frp_client.widgets import (
    ActionButton,
    Card,
    ColorSwatchButton,
    ThemedCheckBox,
    ThemedFontComboBox,
    ThemedLabel,
    ThemedSlider,
    text_label,
)

LABEL_WIDTH = 120


class AccentSwatch(QPushButton):
    """强调色预设色块：点一下就把强调色换成它，当前值会描边。"""

    def __init__(self, code: str, parent=None) -> None:
        super().__init__(parent)
        self._frp_own_font = True
        self._code = code
        self._active = False
        self.setFixedSize(34, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.apply_appearance()

    def code(self) -> str:
        return self._code

    def setActive(self, active: bool) -> None:
        self._active = active
        self.apply_appearance()

    def apply_appearance(self) -> None:
        from PyQt5.QtGui import QColor

        pal = appearance.current().palette()
        border = pal["text_a"] if self._active else pal["border"]
        width = 3 if self._active else 1
        text_color = "#FFFFFF" if QColor(self._code).lightness() < 150 else "#1C191F"
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._code}; color: {text_color};"
            f"  border: {width}px solid {border}; border-radius: 6px; font-size: 10px; }}"
            f"QPushButton:hover {{ border: 2px solid {pal['text_b']}; }}"
        )
        self.setText(self._code.upper().lstrip("#") if self._active else "")


class AppearancePage(ContentPage):
    """外观设置页。"""

    changed = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent, title="外观与设置", padding=44, max_width=1240, spacing=16)

        self._controls: dict[str, object] = {}
        self._choice_getters: dict[str, object] = {}


        columns = QWidget(self.content)
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)

        left = QWidget(columns)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        left_layout.addWidget(self._build_scheme_card())
        left_layout.addWidget(self._build_color_card())
        left_layout.addWidget(self._build_terminal_card())
        left_layout.addStretch(1)

        right = QWidget(columns)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        right_layout.addWidget(self._build_window_card())
        right_layout.addWidget(self._build_font_card())
        right_layout.addWidget(self._build_widget_card())
        right_layout.addWidget(self._build_reset_card())
        right_layout.addStretch(1)

        columns_layout.addWidget(left, 1)
        columns_layout.addWidget(right, 1)
        self.vbox.addWidget(columns, 1)

        self.refresh_controls()

    # ------------------------------------------------------------ 行构造工具

    def _row(self, parent, label_text: str, widget: QWidget, hint: QWidget | None = None) -> QWidget:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = text_label(label_text, 13, "text_d", parent=row)
        label.setFixedWidth(LABEL_WIDTH)
        layout.addWidget(label, 0, Qt.AlignVCenter)
        layout.addWidget(widget, 0, Qt.AlignVCenter)
        if hint is not None:
            layout.addWidget(hint, 1)
        else:
            layout.addStretch(1)
        return row

    def _swatch_row(self, parent, label_text: str, key: str, hint_text: str = "") -> QWidget:
        swatch = ColorSwatchButton(appearance.current().get(key), parent)
        swatch.colorChanged.connect(lambda code, k=key: self._change(k, code))
        self._controls[key] = swatch

        hint = text_label(hint_text, 12, "text_e", parent=parent)
        return self._row(parent, label_text, swatch, hint)

    def _slider_row(self,
                    parent,
                    label_text: str,
                    key: str,
                    minimum: int,
                    maximum: int,
                    step: int = 1,
                    formatter=None,
                    transform=None) -> QWidget:
        """滑条行。transform 在「滑条整数」与「设置值」之间换算，formatter 负责显示。"""
        slider = ThemedSlider(Qt.Horizontal, parent)
        slider.setRange(minimum, maximum)
        slider.setSingleStep(step)
        slider.setPageStep(max(step, (maximum - minimum) // 10))
        slider.setFixedWidth(200)

        value_label = text_label("", 13, "text_b", parent=parent)
        value_label.setFixedWidth(64)

        def to_value(raw: int):
            return transform(raw) if transform else raw

        def on_value(raw: int) -> None:
            value = to_value(raw)
            value_label.setText(formatter(value) if formatter else str(value))
            self._change(key, value)

        slider.valueChanged.connect(on_value)
        self._controls[key] = slider
        self._controls[f"{key}__label"] = value_label
        self._controls[f"{key}__formatter"] = formatter
        self._controls[f"{key}__transform"] = transform

        holder = QWidget(parent)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(10)
        holder_layout.addWidget(slider)
        holder_layout.addWidget(value_label)
        return self._row(parent, label_text, holder)

    def _choice_row(self,
                    parent,
                    label_text: str,
                    key: str,
                    options: list[tuple[str, object]],
                    hint_text: str = "",
                    getter=None,
                    on_change=None) -> QWidget:
        """一排互斥的按钮。

        默认改的是外观设置项；给了 ``on_change`` / ``getter`` 就改别的
        （例如「关闭窗口时」这种行为设置）。
        """
        holder = QWidget(parent)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(6)

        buttons_row = QWidget(holder)
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)

        buttons = []
        for text, value in options:
            width = 96 if len(str(text)) <= 6 else 132
            button = ActionButton.create(text, buttons_row, kind="secondary", height=34, width=width)
            if on_change is None:
                button.clicked.connect(lambda _checked=False, v=value: self._change(key, v))
            else:
                button.clicked.connect(lambda _checked=False, v=value: on_change(v))
            buttons_layout.addWidget(button)
            buttons.append((value, button))
        buttons_layout.addStretch(1)
        holder_layout.addWidget(buttons_row)

        if hint_text:
            # 提示单独占一行，避免把按钮挤出卡片
            hint = text_label(hint_text, 12, "text_e", parent=holder, wrap=True)
            hint.setMinimumHeight(18)
            holder_layout.addWidget(hint)

        self._controls[key] = buttons
        if getter is not None:
            self._choice_getters[key] = getter
        return self._row_wide(parent, label_text, holder)

    def _row_wide(self, parent, label_text: str, widget: QWidget) -> QWidget:
        """标签在左、控件在右并占满剩余宽度的行。"""
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = text_label(label_text, 13, "text_d", parent=row)
        label.setFixedWidth(LABEL_WIDTH)
        layout.addWidget(label, 0, Qt.AlignTop)
        layout.addWidget(widget, 1)
        return row

    # ------------------------------------------------------------ 各张卡片

    def _build_scheme_card(self) -> Card:
        card = Card(self, title="配色方案", icon_name="ic_fluent_dark_theme_regular")

        card.addWidget(self._choice_row(
            card, "方案", "mode",
            [("深色", "dark"), ("亮色", "light")],
            "整体切换深色 / 亮色（会重置下面的配色，字体圆角等设置保留）"))

        accent_row = QWidget(card)
        accent_layout = QHBoxLayout(accent_row)
        accent_layout.setContentsMargins(0, 0, 0, 0)
        accent_layout.setSpacing(8)

        label = text_label("强调色", 13, "text_d", parent=accent_row)
        label.setFixedWidth(LABEL_WIDTH)
        accent_layout.addWidget(label)

        self._accent_swatches: list[AccentSwatch] = []
        for name, code in appearance.ACCENT_PRESETS:
            swatch = AccentSwatch(code, accent_row)
            swatch.setToolTip(f"{name} {code}")
            swatch.clicked.connect(lambda _checked=False, c=code: self._set_accent(c))
            accent_layout.addWidget(swatch)
            self._accent_swatches.append(swatch)

        custom = ActionButton.create("自定义…", accent_row, kind="ghost",
                                     icon_name="ic_fluent_eyedropper_regular", height=30, width=92)
        custom.clicked.connect(self._pick_accent)
        accent_layout.addWidget(custom)
        accent_layout.addStretch(1)

        card.addWidget(accent_row)

        self._accent_hint = text_label("", 12, "text_e", parent=card)
        card.addWidget(self._accent_hint)
        return card

    def _build_color_card(self) -> Card:
        card = Card(self, title="界面配色", icon_name="ic_fluent_color_regular")
        card.addWidget(self._swatch_row(card, "页面背景", "bg_a"))
        card.addWidget(self._swatch_row(card, "卡片背景", "bg_c"))
        card.addWidget(self._swatch_row(card, "输入框背景", "bg_b"))
        card.addWidget(self._swatch_row(card, "边框 / 分隔", "bg_d"))
        card.addWidget(self._swatch_row(card, "悬停底色", "bg_e"))
        card.addWidget(self._swatch_row(card, "标题文字", "text_a"))
        card.addWidget(self._swatch_row(card, "正文文字", "text_b"))
        card.addWidget(self._swatch_row(card, "次要文字", "text_d"))
        card.addWidget(self._swatch_row(card, "弱化文字", "text_e"))
        card.addWidget(self._swatch_row(card, "图标颜色", "icon"))
        return card

    def _build_terminal_card(self) -> Card:
        card = Card(self, title="终端与日志", icon_name="ic_fluent_window_dev_tools_regular")

        card.addWidget(self._swatch_row(card, "终端背景", "terminal_bg"))
        card.addWidget(self._swatch_row(card, "终端文字", "terminal_text"))
        card.addWidget(self._slider_row(card, "终端字号", "terminal_font_size", 11, 20,
                                        formatter=lambda value: f"{value} px"))
        card.addWidget(self._swatch_row(card, "普通日志", "log_normal"))
        card.addWidget(self._swatch_row(card, "错误日志", "log_error"))
        card.addWidget(self._swatch_row(card, "警告日志", "log_warning"))
        card.addWidget(self._swatch_row(card, "成功日志", "log_success"))
        card.addWidget(self._swatch_row(card, "本程序消息", "log_system"))
        return card

    def _build_font_card(self) -> Card:
        card = Card(self, title="字体与缩放", icon_name="ic_fluent_text_font_regular")

        combo = ThemedFontComboBox(card)
        combo.setMinimumWidth(240)
        combo.onChanged(lambda family: self._change("font_family", family))
        self._controls["font_family"] = combo
        card.addWidget(self._row_wide(
            card, "界面字体", combo))

        card.addWidget(self._slider_row(
            card, "文字大小", "font_scale", 85, 125, step=5,
            formatter=lambda value: f"{int(round(float(value) * 100))}%",
            transform=lambda raw: round(raw / 100, 2)))

        card.addWidget(self._choice_row(
            card, "界面缩放", "ui_scale",
            [("100%", 100), ("125%", 125), ("150%", 150), ("175%", 175)],
            "整体放大界面（含组件库控件），重启程序后生效"))

        hint = text_label(
            "文字大小即时生效（范围 85%–125%，过大可能挤压固定高度的控件）；"
            "界面缩放需要重启程序，因为 Qt 只在启动时读取缩放比例。",
            12, "text_e", parent=card, wrap=True)
        hint.setMinimumHeight(20)
        card.addWidget(hint)
        return card

    def _build_window_card(self) -> Card:
        """窗口与托盘：关闭窗口的行为（这项不算外观，存在主配置里）。"""
        card = Card(self, title="窗口与托盘", icon_name="ic_fluent_window_regular")

        def current_action() -> str:
            window = self.window()
            return str(getattr(window, "config", {}).get("close_action") or "tray")

        def set_action(value: str) -> None:
            window = self.window()
            if hasattr(window, "config"):
                window.config["close_action"] = value
                window._save_config()
            self.refresh_controls()

        card.addWidget(self._choice_row(
            card, "关闭窗口时", "close_action",
            [("收进托盘", "tray"), ("最小化到任务栏", "taskbar"), ("直接退出", "quit")],
            "Windows 11 默认会把新托盘图标折叠进「显示隐藏的图标」，找不到图标就选「最小化到任务栏」",
            getter=current_action, on_change=set_action))

        card.addWidget(text_label(
            "· 收进托盘：程序留在后台，内网穿透不断；再双击一次程序图标就能把窗口叫回来。",
            12, "text_e", parent=card, wrap=True))
        card.addWidget(text_label(
            "· 最小化到任务栏：窗口缩到任务栏，任务栏上一定看得见，点一下就回来。",
            12, "text_e", parent=card, wrap=True))
        card.addWidget(text_label(
            "· 直接退出：关窗口就结束程序，同时会结束内网穿透（朋友会掉线）。",
            12, "text_e", parent=card, wrap=True))
        return card

    def _build_widget_card(self) -> Card:
        card = Card(self, title="控件外观", icon_name="ic_fluent_paint_brush_regular")
        card.addWidget(self._slider_row(card, "按钮圆角", "radius_button", 0, 16,
                                        formatter=lambda value: f"{value} px"))
        card.addWidget(self._slider_row(card, "卡片圆角", "radius_card", 0, 20,
                                        formatter=lambda value: f"{value} px"))
        card.addWidget(self._slider_row(card, "输入框圆角", "radius_input", 0, 14,
                                        formatter=lambda value: f"{value} px"))

        self._animation_box = ThemedCheckBox("启用界面动画（移动 / 淡入淡出）", card)
        self._animation_box.toggled.connect(lambda checked: self._change("animations", bool(checked)))
        self._controls["animations"] = self._animation_box
        card.addWidget(self._animation_box)
        card.addWidget(text_label("关掉动画可以让界面响应更快，也能避免低配机器上的卡顿。",
                                  12, "text_e", parent=card, wrap=True))
        return card

    def _build_reset_card(self) -> Card:
        card = Card(self, title="重置与说明", icon_name="ic_fluent_arrow_reset_regular")

        row = QWidget(card)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        reset_button = ActionButton.create("恢复默认外观", row, kind="danger",
                                           icon_name="ic_fluent_arrow_reset_regular", height=38, width=160)
        reset_button.clicked.connect(self._reset)
        layout.addWidget(reset_button)
        layout.addStretch(1)
        card.addWidget(row)

        card.addWidget(text_label(
            "「恢复默认外观」会把当前配色方案下的所有外观项还原（深色 / 亮色各自的默认值）。",
            12, "text_e", parent=card, wrap=True))
        card.addWidget(text_label(
            "所有外观设置都会立即写入配置文件，下次启动自动套用。",
            12, "text_e", parent=card, wrap=True))
        return card

    # ------------------------------------------------------------ 交互

    def _change(self, key: str, value) -> None:
        current = appearance.current()
        if current.get(key) == value:
            return
        if key == "mode":
            current.set_mode(str(value))
        else:
            current.set(key, value)
        self.refresh_controls()
        self.changed.emit()

    def _set_accent(self, code: str) -> None:
        self._change("accent", code)

    def _pick_accent(self) -> None:
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QColorDialog

        current = appearance.current()
        chosen = QColorDialog.getColor(QColor(current.get("accent")), self.window(), "选择强调色")
        if chosen.isValid():
            self._change("accent", chosen.name().upper())

    def _reset(self) -> None:
        appearance.current().reset()
        self.refresh_controls()
        self.changed.emit()

    def refresh_controls(self) -> None:
        """把控件同步成当前设置（不触发信号）。"""
        current = appearance.current()

        for key, control in self._controls.items():
            if key.endswith("__label") or key.endswith("__display"):
                continue
            # 有的控件管的不是外观项（例如「关闭窗口时」），用 getter 取当前值
            getter = self._choice_getters.get(key)
            value = getter() if getter is not None else current.get(key)

            if isinstance(control, ColorSwatchButton):
                control.blockSignals(True)
                control.setColor(str(value))
                control.blockSignals(False)
                continue

            if isinstance(control, ThemedSlider):
                transform = self._controls.get(f"{key}__transform")
                formatter = self._controls.get(f"{key}__formatter")
                label = self._controls.get(f"{key}__label")
                raw = int(round(float(value) * 100)) if key == "font_scale" else int(value)
                control.blockSignals(True)
                control.setValue(raw)
                control.blockSignals(False)
                if label is not None:
                    shown = transform(raw) if transform else raw
                    label.setText(formatter(shown) if formatter else str(shown))
                continue

            if isinstance(control, ThemedFontComboBox):
                control.combo.blockSignals(True)
                control.setCurrentText(str(value))
                control.combo.blockSignals(False)
                continue

            if isinstance(control, ThemedCheckBox):
                control.blockSignals(True)
                control.setChecked(bool(value))
                control.blockSignals(False)
                continue

            if isinstance(control, list):  # 互斥按钮组
                for option_value, button in control:
                    active = option_value == value
                    button._frp_kind = "primary" if active else "secondary"
                    ActionButton.style_button(button, button._frp_kind)
                continue

        # 强调色：预设色块上标出当前值
        accent = str(current.get("accent"))
        for swatch in getattr(self, "_accent_swatches", []):
            swatch.setActive(swatch.code().upper() == accent.upper())
        if hasattr(self, "_accent_hint"):
            self._accent_hint.setText(f"当前强调色：{accent.upper()}"
                                      "　·　按钮、选中态、滑块、进度条都会跟着变")

    def apply_appearance(self) -> None:
        """换肤后同步控件自身的显示（按钮的选中态、色块等）。"""
        self.refresh_controls()
