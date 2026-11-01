"""新手引导：浮在主界面上的流式（打字机）向导。

* 文字一个字一个字打出来，打完之前按钮是「显示完整」，打完变成「下一步」；
* 每一步可以顺带把主界面切到对应页面（“讲哪就切到哪”）；
* 随时可以点「跳过引导」或者按 Esc 直接跳过；
* 看完（或跳过）会记到配置文件里，下次启动不再自动弹出，也可以在「使用帮助」页重播。
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from frp_client.widgets import ActionButton, Card, ThemedLabel, ThemedToolButton, text_label

# 打字机速度：每 tick 打出的字符数（间隔 16ms）
CHARS_PER_TICK = 2
TICK_MS = 16

PANEL_WIDTH = 780
PANEL_HEIGHT = 214
TEXT_HEIGHT = 96


@dataclass(frozen=True)
class GuideStep:
    """一步引导：标题 + 正文 + 该步对应的主界面页面。"""

    title: str
    text: str
    page: int = 0


STEPS: list[GuideStep] = [
    GuideStep(
        title="欢迎使用 frp-panel 可视化客户端",
        text=(
            "这个程序帮你把 frp-panel 网页上拿到的启动命令跑起来，"
            "把《我的世界》局域网世界分享给朋友一起玩。\n"
            "整个过程只有三步：先开局域网 → 复制启动命令 → 粘贴并启动。\n"
            "点「下一步」，我带你走一遍（随时可以点「跳过引导」）。"
        ),
        page=0,
    ),
    GuideStep(
        title="第 1 步 · 先开《我的世界》局域网",
        text=(
            "进入单人世界后按 ESC →「对局域网开放」，聊天栏会提示端口号（一般是 25565）。\n"
            "顺序很重要：一定要先开局域网，再启动内网穿透，朋友才连得进来。\n"
            "面板里隧道的「本地端口」也要跟这个端口一致，不一致就改成它。"
        ),
        page=0,
    ),
    GuideStep(
        title="第 2 步 · 到网页复制启动命令",
        text=(
            "点第 1 步的「打开网页」登录面板 → 打开「客户端」页面 → 复制你的客户端启动命令。\n"
            "命令长这样：frp-panel client -s xxxx-xxxx -i 你的客户端ID --api-url … --rpc-url …\n"
            "整行复制下来就行，不用自己改内容。"
        ),
        page=0,
    ),
    GuideStep(
        title="第 3 步 · 粘贴并启动",
        text=(
            "点第 2 步的「粘贴」按钮读取剪贴板，"
            "程序会自动把开头的 frp-panel 改写成本机的 ./frp-panel-windows-amd64.exe。\n"
            "然后勾选第 3 步的确认框，点「启动内网穿透」。\n"
            "没勾确认框时会拦一下——那是在提醒你回去开局域网。"
        ),
        page=0,
    ),
    GuideStep(
        title="第 4 步 · 看状态和日志",
        text=(
            "日志会实时打在这里（也可以在「启动面板」右侧看）。\n"
            "状态灯变绿、出现 login to server success 或 start proxy success，就说明隧道通了。\n"
            "这时把面板里这条隧道的公网地址发给朋友，"
            "他用「多人游戏 → 直接连接」输入地址就能进服。"
        ),
        page=1,
    ),
    GuideStep(
        title="第 5 步 · 托盘、退出与外观",
        text=(
            "点窗口的 × 不会退出，程序会缩到桌面右下角托盘继续跑；"
            "右键托盘图标可以「结束穿透」或「退出」。\n"
            "这个「外观设置」页面能调配色、强调色、字体字号、圆角和终端配色，改完立刻生效。\n"
            "引导就到这里，祝开黑愉快！点「开始使用」继续。"
        ),
        page=2,
    ),
]


class GuideOverlay(Card):
    """浮在界面上的引导面板。"""

    finished = pyqtSignal(bool)     # True = 看完，False = 跳过
    stepChanged = pyqtSignal(int)   # 当前步骤对应的页面索引

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="", spacing=8)

        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)

        self._index = 0
        self._shown_chars = 0
        self._full_text = ""
        self._running = False

        layout = self.layout()
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(8)

        # ---- 标题行
        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self._title_label = text_label("", 16, "text_a", bold=True, parent=header)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)

        self._step_label = text_label("", 13, "text_e", parent=header)
        header_layout.addWidget(self._step_label)

        close_button = ThemedToolButton("✕", header, height=24)
        close_button.setFixedWidth(28)
        close_button.setToolTip("跳过引导（Esc）")
        close_button.clicked.connect(self.skip)
        header_layout.addWidget(close_button)

        layout.addWidget(header)

        # ---- 正文（流式输出）
        self._text_label = ThemedLabel("", 14, "text_c", wrap=True, parent=self)
        self._text_label.setFixedHeight(TEXT_HEIGHT)
        self._text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self._text_label)

        # ---- 底部按钮
        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)

        self._skip_button = ActionButton.create("跳过引导", footer, kind="ghost", height=36, width=110)
        self._skip_button.clicked.connect(self.skip)
        footer_layout.addWidget(self._skip_button)
        footer_layout.addStretch(1)

        self._prev_button = ActionButton.create("上一步", footer, kind="secondary", height=36, width=100)
        self._prev_button.clicked.connect(self.previous_step)
        footer_layout.addWidget(self._prev_button)

        self._next_button = ActionButton.create("下一步", footer, kind="primary", height=36, width=130)
        self._next_button.clicked.connect(self.next_step)
        footer_layout.addWidget(self._next_button)

        layout.addWidget(footer)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._stream_tick)

        self.hide()

    # ------------------------------------------------------------ 流程控制

    def start(self, index: int = 0) -> None:
        """开始（或重新开始）引导。"""
        self._index = max(0, min(index, len(STEPS) - 1))
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._apply_step()

    def skip(self) -> None:
        self._timer.stop()
        self._running = False
        self.hide()
        self.finished.emit(False)

    def next_step(self) -> None:
        if self._running:
            # 还在打字：先把这一步打完，别让用户漏看内容
            self._finish_typing()
            return

        if self._index >= len(STEPS) - 1:
            self._timer.stop()
            self.hide()
            self.finished.emit(True)
            return

        self._index += 1
        self._apply_step()

    def previous_step(self) -> None:
        if self._index <= 0:
            return
        self._index -= 1
        self._apply_step()

    # ------------------------------------------------------------ 渲染

    def _apply_step(self) -> None:
        step = STEPS[self._index]

        self._title_label.setText(step.title)
        self._step_label.setText(f"第 {self._index + 1} / {len(STEPS)} 步")

        self._prev_button.setEnabled(self._index > 0)
        ActionButton.set_muted(self._prev_button, self._index <= 0)

        self._next_button.setText("开始使用" if self._index == len(STEPS) - 1 else "下一步")

        self.stepChanged.emit(step.page)

        # 打字机开始
        self._full_text = step.text
        self._shown_chars = 0
        self._running = True
        self._text_label.setText("")
        self._next_button.setText("显示完整")
        self._timer.start()

    def _stream_tick(self) -> None:
        self._shown_chars += CHARS_PER_TICK
        if self._shown_chars >= len(self._full_text):
            self._finish_typing()
            return

        self._text_label.setText(self._full_text[:self._shown_chars] + "▌")

    def _finish_typing(self) -> None:
        self._timer.stop()
        self._running = False
        self._text_label.setText(self._full_text)
        self._next_button.setText("开始使用" if self._index == len(STEPS) - 1 else "下一步")

    # ------------------------------------------------------------ 其它

    def is_streaming(self) -> bool:
        return self._running

    def current_index(self) -> int:
        return self._index

    def apply_appearance(self) -> None:
        """引导面板要比普通卡片更「跳」一点：浅一档的底色 + 强调色描边 + 投影。"""
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect

        from frp_client import appearance

        pal = appearance.current().palette()
        self.setStyleSheet(
            f"#{self.objectName()} {{"
            f"  background-color: {pal['bg_e']};"
            f"  border: 1px solid {pal['accent']};"
            f"  border-radius: {int(pal['radius_card']) + 2}px;"
            f"}}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120 if not pal["is_light"] else 70))
        self.setGraphicsEffect(shadow)

    def reposition(self) -> None:
        """贴着主窗口底部居中放。"""
        parent = self.parentWidget()
        if parent is None:
            return
        x = max(12, (parent.width() - self.width()) // 2)
        y = max(12, parent.height() - self.height() - 22)
        self.move(x, y)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.skip()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next_step()
            return
        if event.key() == Qt.Key_Left:
            self.previous_step()
            return
        super().keyPressEvent(event)
