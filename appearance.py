"""外观设置：整套界面外观的唯一数据源。

设计思路
--------
* 所有可调外观都放在一个扁平的字典里（颜色 / 字体 / 圆角 / 动画 / 缩放），
  保存到 ``frp_client_config.json`` 的 ``appearance`` 字段。
* :meth:`Appearance.apply` 负责把这份设置推给三处：

  1. **组件库全局色板** ``SiGlobal.siui.colors`` —— 组件库内部所有控件都持有
     对它的引用（``SiColorGroup(reference=...)``），原地修改后调用
     ``reloadAllWindowsStyleSheet()`` 即可整体换肤，暗色 / 亮色主题就是这样切的；
  2. **组件库控件字体** —— 逐个控件按比例缩放字号、替换字体族，
     并记下原始字号避免重复放大；
  3. **本程序自己的控件** —— 遍历控件树，调用它们各自的
     ``apply_appearance()``（卡片、标签、按钮、终端……都实现了这个方法）。

  因此往后要新增外观项，只要加一个键、在控件里读它就行。
"""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal

# --------------------------------------------------------------------------- 默认值

DARK_DEFAULTS: dict[str, Any] = {
    "mode": "dark",
    "accent": "#B07CC6",
    "bg_a": "#1C191F",
    "bg_b": "#25222A",
    "bg_c": "#332E38",
    "bg_d": "#403A46",
    "bg_e": "#4C4554",
    "text_a": "#E5E5E5",
    "text_b": "#DFDFDF",
    "text_c": "#C7C7C7",
    "text_d": "#AFAFAF",
    "text_e": "#979797",
    "icon": "#DFDFDF",
    "terminal_bg": "#14121A",
    "terminal_text": "#C9C3CF",
    "log_normal": "#C9C3CF",
    "log_error": "#E06C75",
    "log_warning": "#E5C07B",
    "log_system": "#8C7FA8",
    "log_success": "#98C379",
    "font_family": "Microsoft YaHei UI",
    "font_scale": 1.0,
    "mono_family": "Cascadia Mono",
    "terminal_font_size": 13,
    "radius_card": 8,
    "radius_button": 7,
    "radius_input": 6,
    "animations": True,
    "ui_scale": 100,
}

# 亮色方案参考组件库自带的 BrightColorGroup
LIGHT_DEFAULTS: dict[str, Any] = {
    **DARK_DEFAULTS,
    "mode": "light",
    "accent": "#2AA9A0",
    "bg_a": "#D6D6D6",
    "bg_b": "#E4E4E6",
    "bg_c": "#EDEDEF",
    "bg_d": "#F7F7F8",
    "bg_e": "#FFFFFF",
    "text_a": "#171D1B",
    "text_b": "#2E3432",
    "text_c": "#363D3B",
    "text_d": "#464D4B",
    "text_e": "#5A615F",
    "icon": "#494F4D",
    "terminal_bg": "#F4F4F6",
    "terminal_text": "#2E3432",
    "log_normal": "#2E3432",
    "log_error": "#C0392B",
    "log_warning": "#9A6A00",
    "log_system": "#6A5B8C",
    "log_success": "#2E7D32",
}

# 强调色预设
ACCENT_PRESETS: list[tuple[str, str]] = [
    ("紫", "#B07CC6"),
    ("蓝", "#61AFEF"),
    ("青", "#4FC3C7"),
    ("绿", "#98C379"),
    ("橙", "#E5A76B"),
    ("粉", "#E08BB0"),
    ("红", "#E06C75"),
    ("靛", "#8C7FE0"),
]

# 这些键跟随「深色 / 亮色」方案整体切换；其余设置（字体、圆角、缩放……）保持不变
COLOR_KEYS = (
    "accent",
    "bg_a", "bg_b", "bg_c", "bg_d", "bg_e",
    "text_a", "text_b", "text_c", "text_d", "text_e",
    "icon",
    "terminal_bg", "terminal_text",
    "log_normal", "log_error", "log_warning", "log_system", "log_success",
)

# --------------------------------------------------------------------------- 颜色工具


def _parse(code: str) -> tuple[int, int, int, int]:
    """把 #RRGGBB / #AARRGGBB 解析成 (a, r, g, b)。"""
    data = (code or "").lstrip("#")
    if len(data) == 3:
        data = "".join(ch * 2 for ch in data)
    if len(data) == 6:
        data = "FF" + data
    if len(data) != 8:
        return 255, 255, 255, 255
    try:
        a, r, g, b = (int(data[i:i + 2], 16) for i in (0, 2, 4, 6))
    except ValueError:
        return 255, 255, 255, 255
    return a, r, g, b


def _code(a: int, r: int, g: int, b: int) -> str:
    a, r, g, b = (max(0, min(255, int(round(value)))) for value in (a, r, g, b))
    if a >= 255:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{a:02X}{r:02X}{g:02X}{b:02X}"


def mix(fore: str, back: str, weight: float = 0.5) -> str:
    """按 weight 混合两个颜色（weight 是 fore 的占比）。"""
    a1, r1, g1, b1 = _parse(fore)
    a2, r2, g2, b2 = _parse(back)
    weight = max(0.0, min(1.0, weight))
    return _code(a1 * weight + a2 * (1 - weight),
                 r1 * weight + r2 * (1 - weight),
                 g1 * weight + g2 * (1 - weight),
                 b1 * weight + b2 * (1 - weight))


def with_alpha(code: str, factor: float) -> str:
    """按比例调整透明度（用于半透明遮罩）。"""
    a, r, g, b = _parse(code)
    return _code(a * max(0.0, min(1.0, factor)), r, g, b)


def luminance(code: str) -> float:
    _, r, g, b = _parse(code)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def contrast_text(code: str, light: str = "#FFFFFF", dark: str = "#16121A") -> str:
    """给一个背景色挑选可读的文字色。"""
    return dark if luminance(code) > 0.62 else light


def normalize(code: str) -> str:
    """统一成 #RRGGBB 大写形式，便于展示。"""
    a, r, g, b = _parse(code)
    return _code(255, r, g, b)


def is_hex_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    data = value.lstrip("#")
    return len(data) in (3, 6, 8) and all(ch in "0123456789abcdefABCDEF" for ch in data)


# --------------------------------------------------------------------------- 外观对象


class Appearance(QObject):
    """全部外观设置 + 应用到界面的逻辑。"""

    changed = pyqtSignal(str)  # 参数是变化的键，批量应用时为 "*"

    def __init__(self, data: dict | None = None) -> None:
        super().__init__()
        self._data: dict[str, Any] = dict(DARK_DEFAULTS)
        if data:
            self.update(data, notify=False)

    # ------------------------------------------------------------ 读写

    def data(self) -> dict[str, Any]:
        return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, notify: bool = True) -> None:
        if key not in DARK_DEFAULTS:
            raise KeyError(f"未知的外观设置项：{key}")
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if notify:
            self.changed.emit(key)

    def update(self, mapping: dict, notify: bool = True) -> None:
        changed = False
        for key, value in (mapping or {}).items():
            if key in DARK_DEFAULTS and self._data.get(key) != value:
                self._data[key] = value
                changed = True
        if changed and notify:
            self.changed.emit("*")

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def is_light(self) -> bool:
        return self._data.get("mode") == "light"

    def mode_defaults(self, mode: str | None = None) -> dict[str, Any]:
        mode = mode or self._data.get("mode", "dark")
        return dict(LIGHT_DEFAULTS if mode == "light" else DARK_DEFAULTS)

    def set_mode(self, mode: str, notify: bool = True) -> None:
        """切换深色 / 亮色：只重置配色相关的键，字体圆角等设置保留。"""
        if mode not in ("dark", "light"):
            raise ValueError(f"未知的配色方案：{mode}")

        defaults = self.mode_defaults(mode)
        for key in COLOR_KEYS:
            self._data[key] = defaults[key]
        self._data["mode"] = mode
        if notify:
            self.changed.emit("*")

    def reset(self, notify: bool = True) -> None:
        """恢复当前方案的默认外观。"""
        mode = self._data.get("mode", "dark")
        self._data = self.mode_defaults(mode)
        if notify:
            self.changed.emit("*")

    def is_default(self) -> bool:
        return self._data == self.mode_defaults()

    # ------------------------------------------------------------ 派生色板

    def palette(self) -> dict[str, Any]:
        """界面控件直接使用的颜色表（在原始设置基础上派生）。"""
        data = self._data
        light = self.is_light()

        accent = data["accent"]
        bg_a, bg_b, bg_c, bg_d, bg_e = (data["bg_a"], data["bg_b"], data["bg_c"],
                                        data["bg_d"], data["bg_e"])
        text_b, text_d, text_e = data["text_b"], data["text_d"], data["text_e"]
        log_error = data["log_error"]

        danger_weight = 0.92 if light else 0.55
        danger_bg = mix(log_error, bg_a, danger_weight)
        muted_bg = mix(bg_c, bg_a, 0.45)
        accent_bg = mix(accent, bg_a, 0.5 if light else 0.42)

        return {
            **data,
            "is_light": light,
            # 结构色
            "page_bg": bg_a,
            "card_bg": bg_c,
            "input_bg": bg_b,
            "hover_bg": bg_e,
            "border": bg_d,
            "terminal_selection": mix(accent, data["terminal_bg"], 0.4),
            # 强调色系
            "accent": accent,
            "accent_bg": accent_bg,
            "accent_text": contrast_text(accent_bg),
            "accent_hover": with_alpha("#FFFFFF" if not light else "#000000", 0.16),
            "accent_press": with_alpha("#FFFFFF" if not light else "#000000", 0.28),
            "accent_soft": with_alpha(accent, 0.35),
            # 次级按钮
            "button_bg": bg_e,
            "button_text": text_b,
            "ghost_text": text_d,
            # 危险按钮
            "danger": log_error,
            "danger_bg": danger_bg,
            "danger_text": contrast_text(danger_bg),
            # 置灰（不可用）
            "muted_bg": muted_bg,
            "muted_text": mix(text_e, bg_c, 0.55),
            # 终端
            "terminal_bg": data["terminal_bg"],
            "terminal_text": data["terminal_text"],
            "log_normal": data["log_normal"],
            "log_error": data["log_error"],
            "log_warning": data["log_warning"],
            "log_system": data["log_system"],
            "log_success": data["log_success"],
            # 滚动条
            "scroll_bar": "#40000000" if light else "#50FFFFFF",
        }

    # ------------------------------------------------------------ 应用到界面

    def apply(self, root=None) -> None:
        """把当前设置应用到整个界面。"""
        self.apply_library_colors()
        self.apply_application_font(root)
        if root is not None:
            self.apply_widget_tree(root)

    def apply_library_colors(self) -> None:
        """把色板写进组件库的全局色组，并让所有组件库控件重载样式。"""
        from siui.core import SiColor, SiGlobal

        colors = SiGlobal.siui.colors
        c = self.palette()
        light = c["is_light"]

        # 界面底色 / 文字
        colors.assign(SiColor.INTERFACE_BG_A, c["bg_a"])
        colors.assign(SiColor.INTERFACE_BG_B, c["bg_b"])
        colors.assign(SiColor.INTERFACE_BG_C, c["bg_c"])
        colors.assign(SiColor.INTERFACE_BG_D, c["bg_d"])
        colors.assign(SiColor.INTERFACE_BG_E, c["bg_e"])
        colors.assign(SiColor.TEXT_A, c["text_a"])
        colors.assign(SiColor.TEXT_B, c["text_b"])
        colors.assign(SiColor.TEXT_C, c["text_c"])
        colors.assign(SiColor.TEXT_D, c["text_d"])
        colors.assign(SiColor.TEXT_E, c["text_e"])
        colors.assign(SiColor.TEXT_THEME, mix(c["accent"], c["text_a"], 0.7))

        # 主题色
        colors.assign(SiColor.THEME, c["accent"])
        colors.assign(SiColor.THEME_TRANSITION_A, mix(c["accent"], c["bg_a"], 0.55))
        colors.assign(SiColor.THEME_TRANSITION_B, mix(c["accent"], c["bg_b"], 0.55))

        # 图标
        colors.assign(SiColor.SVG_NORMAL, c["icon"])
        colors.assign(SiColor.SVG_THEME, c["accent"])
        SiGlobal.siui.iconpack.setDefaultColor(c["icon"])

        # 容器 / 浮层
        colors.assign(SiColor.LAYER_DIM, "#60000000")
        colors.assign(SiColor.TOOLTIP_BG, with_alpha(c["bg_e"], 0.94))
        colors.assign(SiColor.MENU_BG, c["card_bg"])
        colors.assign(SiColor.TITLE_INDICATOR, c["accent"])
        colors.assign(SiColor.TITLE_HIGHLIGHT, with_alpha(c["accent"], 0.35))

        # 按钮
        colors.assign(SiColor.BUTTON_IDLE, "#00000000" if light else "#00FFFFFF")
        colors.assign(SiColor.BUTTON_HOVER, "#12000000" if light else "#10FFFFFF")
        colors.assign(SiColor.BUTTON_FLASH, "#22000000" if light else "#20FFFFFF")
        colors.assign(SiColor.BUTTON_PANEL, c["bg_e"])
        colors.assign(SiColor.BUTTON_SHADOW, mix(c["bg_c"], "#000000", 0.9 if not light else 0.75))
        colors.assign(SiColor.BUTTON_ON, mix(c["accent"], "#000000", 0.4))
        colors.assign(SiColor.BUTTON_OFF, mix(c["accent"], "#FFFFFF", 0.4))
        colors.assign(SiColor.BUTTON_THEMED_BG_A, mix(c["accent"], "#000000", 0.55))
        colors.assign(SiColor.BUTTON_THEMED_BG_B, c["accent"])
        colors.assign(SiColor.BUTTON_THEMED_SHADOW_A, mix(c["accent"], "#000000", 0.72))
        colors.assign(SiColor.BUTTON_THEMED_SHADOW_B, mix(c["accent"], "#000000", 0.5))
        colors.assign(SiColor.BUTTON_TEXT_BUTTON_IDLE, mix(c["accent"], c["text_b"], 0.5))
        colors.assign(SiColor.BUTTON_TEXT_BUTTON_FLASH, c["accent"])
        colors.assign(SiColor.BUTTON_TEXT_BUTTON_HOVER, mix(c["accent"], "#FFFFFF", 0.5))

        # 选择类控件
        colors.assign(SiColor.RADIO_BUTTON_UNCHECKED, c["bg_b"])
        colors.assign(SiColor.RADIO_BUTTON_CHECKED, c["accent"])
        colors.assign(SiColor.CHECKBOX_SVG, c["bg_a"])
        colors.assign(SiColor.CHECKBOX_UNCHECKED, c["text_e"])
        colors.assign(SiColor.CHECKBOX_CHECKED, c["accent"])
        colors.assign(SiColor.SWITCH_DEACTIVATE, c["bg_d"] if not light else "#D2D2D2")
        colors.assign(SiColor.SWITCH_ACTIVATE, c["bg_a"])

        # 长按按钮 / 侧边消息 / 进度条
        colors.assign(SiColor.BUTTON_LONG_PRESS_PANEL, mix(c["log_error"], c["bg_a"], 0.5))
        colors.assign(SiColor.BUTTON_LONG_PRESS_SHADOW, mix(c["log_error"], c["bg_a"], 0.3))
        colors.assign(SiColor.BUTTON_LONG_PRESS_PROGRESS, c["log_error"])
        colors.assign(SiColor.SIDE_MSG_THEME_NORMAL, c["bg_e"])
        colors.assign(SiColor.SIDE_MSG_THEME_INFO, c["accent"])
        colors.assign(SiColor.SIDE_MSG_THEME_SUCCESS, c["log_success"])
        colors.assign(SiColor.SIDE_MSG_THEME_WARNING, c["log_warning"])
        colors.assign(SiColor.SIDE_MSG_THEME_ERROR, c["log_error"])
        colors.assign(SiColor.SIDE_MSG_FLASH, "#90FFFFFF" if not light else "#90FFFFFF")
        colors.assign(SiColor.PROGRESS_BAR_TRACK, c["bg_b"])
        colors.assign(SiColor.PROGRESS_BAR_PROCESSING, c["accent"])
        colors.assign(SiColor.PROGRESS_BAR_COMPLETING, c["log_success"])
        colors.assign(SiColor.PROGRESS_BAR_PAUSED, c["text_e"])
        colors.assign(SiColor.PROGRESS_BAR_FLASHES, "#FFFFFF")

        # 滚动条
        colors.assign(SiColor.SCROLL_BAR, c["scroll_bar"])

        SiGlobal.siui.reloadAllWindowsStyleSheet()

    def apply_application_font(self, root=None) -> None:
        """设置全局字体，并把已存在的控件按比例缩放字号、替换字体族。"""
        from PyQt5.QtGui import QFont
        from PyQt5.QtWidgets import QApplication, QWidget

        family = self.get("font_family")
        scale = float(self.get("font_scale") or 1.0)

        application = QApplication.instance()
        if application is not None:
            font = QFont()
            font.setFamilies([family])
            font.setPixelSize(max(9, round(14 * scale)))
            application.setFont(font)

        if root is None:
            return

        targets = [root, *root.findChildren(QWidget)]
        for widget in targets:
            if getattr(widget, "_frp_own_font", False):
                continue  # 自己管理字体的控件（终端等）跳过
            try:
                font = widget.font()
                pixel = font.pixelSize()
            except Exception:  # noqa: BLE001
                continue

            if pixel and pixel > 0:
                base = getattr(widget, "_frp_base_font_px", None)
                if base is None:
                    base = pixel
                    try:
                        widget._frp_base_font_px = base
                    except Exception:  # noqa: BLE001
                        base = pixel
                new_pixel = max(8, round(base * scale))
            else:
                new_pixel = None

            new_font = QFont(font)
            new_font.setFamilies([family])
            if new_pixel:
                new_font.setPixelSize(new_pixel)
            try:
                widget.setFont(new_font)
            except Exception:  # noqa: BLE001
                continue

            # 组件库里「字号跟着文本调整大小」的标签需要重新量一次尺寸，
            # 否则字号变大后文字会被旧宽度裁掉
            try:
                from siui.core import Si

                if (hasattr(widget, "isSiliconWidgetFlagOn")
                        and widget.isSiliconWidgetFlagOn(Si.AdjustSizeOnTextChanged)):
                    widget.adjustSize()
            except Exception:  # noqa: BLE001
                pass

        self._apply_animation_flags(root)

    def _apply_animation_flags(self, root) -> None:
        """动画开关：控制组件库里「移动 / 缩放 / 淡入」是否带动画。"""
        from PyQt5.QtWidgets import QWidget

        from siui.core import Si

        enabled = bool(self.get("animations"))
        targets = [root, *root.findChildren(QWidget)]
        for widget in targets:
            setter = getattr(widget, "setSiliconWidgetFlag", None)
            if not callable(setter):
                continue
            try:
                setter(Si.InstantMove, not enabled)
                setter(Si.InstantResize, not enabled)
                setter(Si.InstantSetOpacity, not enabled)
            except Exception:  # noqa: BLE001
                pass

    def apply_widget_tree(self, root) -> None:
        """遍历控件树，调用每个控件的 apply_appearance()。"""
        from PyQt5.QtWidgets import QWidget

        errors: list[str] = []
        targets = [root, *root.findChildren(QWidget)]
        for widget in targets:
            applier = getattr(widget, "apply_appearance", None)
            if not callable(applier):
                continue
            try:
                applier()
            except Exception as error:  # noqa: BLE001 - 单个控件出错不影响整体换肤
                errors.append(f"{type(widget).__name__}: {error}")

        if errors:
            print("应用外观时出现问题：", "; ".join(errors[:5]))


# --------------------------------------------------------------------------- 单例


_INSTANCE: Appearance | None = None


def init(data: dict | None = None) -> Appearance:
    """初始化（或更新）全局外观对象。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Appearance(data)
    elif data:
        _INSTANCE.update(data, notify=False)
    return _INSTANCE


def current() -> Appearance:
    """取全局外观对象。"""
    if _INSTANCE is None:
        return init()
    return _INSTANCE


def color(key: str, default: str = "#DFDFDF") -> str:
    """快捷读取派生色板里的颜色。"""
    return current().palette().get(key, default)


def font_scale() -> float:
    return float(current().get("font_scale") or 1.0)
