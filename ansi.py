"""ANSI 转义序列处理：把 frp-panel 的彩色日志转换成终端可以显示的 HTML。

日志配色（普通 / 错误 / 警告 / 系统 / 成功）都取自外观设置，
所以在外观设置页里改一下「日志配色」就能立刻生效。
"""

from __future__ import annotations

import html
import re

from frp_client import appearance

# 形如 \x1b[34m / \x1b[0m / \x1b[90m 的 SGR 序列
SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
# 其它终端控制序列（光标移动、清屏等），统一丢弃
OTHER_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

# xterm 基本色 -> 展示用色号（frp-panel 自己在日志里打的颜色）
BASIC_COLORS = {
    30: "#5C6370", 31: "#E06C75", 32: "#98C379", 33: "#E5C07B",
    34: "#61AFEF", 35: "#C678DD", 36: "#56B6C2", 37: "#DCDFE4",
    90: "#767676", 91: "#FF7B86", 92: "#B6E39A", 93: "#FFD68A",
    94: "#82C7FF", 95: "#E29BE8", 96: "#74D3DE", 97: "#FFFFFF",
}

FALLBACK_COLORS = {
    "log_normal": "#C9C3CF",
    "log_error": "#E06C75",
    "log_warning": "#E5C07B",
    "log_system": "#8C7FA8",
    "log_success": "#98C379",
}


def log_color(key: str) -> str:
    """读取日志配色（跟随外观设置）。"""
    return appearance.current().palette().get(key, FALLBACK_COLORS.get(key, "#C9C3CF"))


def strip_ansi(text: str) -> str:
    """删除所有 ANSI 转义序列。"""
    return OTHER_ESCAPE_RE.sub("", SGR_RE.sub("", text or ""))


def ansi_to_html(text: str, default_color: str | None = None) -> str:
    """把一行带 ANSI 颜色的文本转换成 HTML（保留颜色）。"""
    default_color = default_color or log_color("log_normal")
    text = OTHER_ESCAPE_RE.sub("", text or "")
    text = text.rstrip("\r\n")
    if not text:
        return ""

    pieces: list[str] = []
    current_color: str | None = None
    bold = False
    position = 0

    for match in SGR_RE.finditer(text):
        chunk = text[position:match.start()]
        if chunk:
            pieces.append(_wrap(chunk, current_color or default_color, bold))
        position = match.end()

        codes = [int(code) for code in match.group(1).split(";") if code != ""] or [0]
        for code in codes:
            if code == 0:
                current_color, bold = None, False
            elif code == 1:
                bold = True
            elif code == 2:
                bold = False
            elif code == 22:
                bold = False
            elif code == 39:
                current_color = None
            elif code in BASIC_COLORS:
                current_color = BASIC_COLORS[code]
            elif 40 <= code <= 47:
                pass  # 背景色暂不处理，保持终端背景统一
            elif code in (49,):
                pass

    tail = text[position:]
    if tail:
        pieces.append(_wrap(tail, current_color or default_color, bold))

    return "".join(pieces)


def _wrap(chunk: str, color: str, bold: bool) -> str:
    escaped = html.escape(chunk, quote=False)
    style = f"color:{color}"
    if bold:
        style += ";font-weight:600"
    return f'<span style="{style}">{escaped}</span>'


def plain_message_html(text: str, color: str | None = None, prefix: str = "[GUI]") -> str:
    """把程序自己产生的消息转成 HTML。"""
    color = color or log_color("log_system")
    escaped = html.escape(text, quote=False)
    prefix_html = ""
    if prefix:
        prefix_html = f'<span style="color:{log_color("log_system")}">{html.escape(prefix, quote=False)} </span>'
    return f'{prefix_html}<span style="color:{color}">{escaped}</span>'


def detect_level(line: str) -> str:
    """粗略判断一行的日志级别，用于状态提示。"""
    text = strip_ansi(line).lower()
    if "[error]" in text or "error:" in text or "panic" in text or "fatal" in text:
        return "error"
    if "[warn]" in text or "warning" in text:
        return "warning"
    if "success" in text or "连接成功" in text:
        return "success"
    return "info"
