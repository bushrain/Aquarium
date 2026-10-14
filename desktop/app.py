"""桌面鱼缸主窗口：无边框、半透明圆角，鱼缸 + 悬浮 UI 组装。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from .backend import BackendClient
from .panel import ChipBar, ControlBar
from .tank import TankWidget

STYLE = """
* { font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif; }
QWidget { color: #eaf7f7; font-size: 12px; }
#chip {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(16,30,38,175), stop:1 rgba(6,14,20,150));
    border: 1px solid rgba(255,255,255,38);
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    color: #e4f6f6;
}
#ControlBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(14,28,36,205), stop:1 rgba(5,12,17,195));
    border: 1px solid rgba(140,220,220,48);
    border-radius: 20px;
}
#Popover, #Banner {
    background: rgba(8,18,24,236);
    border: 1px solid rgba(255,255,255,46);
    border-radius: 14px;
}
#ModeHint {
    background: rgba(53,208,186,42);
    border: 1px solid rgba(120,255,230,120);
    border-radius: 12px;
    padding: 4px 14px;
    font-size: 12px;
    color: #d8fff8;
}
QPushButton#pill {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(255,255,255,32), stop:1 rgba(255,255,255,12));
    border: 1px solid rgba(255,255,255,48);
    border-radius: 16px;
    padding: 7px 14px;
    font-size: 13px;
    color: #eaf7f7;
}
QPushButton#pill:hover {
    background: rgba(255,255,255,42);
    border: 1px solid rgba(255,255,255,82);
}
QPushButton#pill:pressed { background: rgba(255,255,255,55); }
QPushButton#pill:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(53,208,186,72), stop:1 rgba(28,140,128,58));
    border: 1px solid rgba(120,255,230,190);
    color: #d8fff8;
}
QPushButton#danger {
    background: rgba(244,100,110,55);
    border: 1px solid rgba(244,100,110,150);
    border-radius: 12px;
    padding: 6px 10px;
    font-size: 12px;
    color: #ffe3e6;
}
QPushButton#danger:hover { background: rgba(244,100,110,85); }
#winbtn {
    background: rgba(6,16,22,150);
    border: 1px solid rgba(255,255,255,40);
    border-radius: 11px;
    font-size: 11px;
    color: #eaf7f7;
}
#winbtn:hover { background: rgba(255,255,255,40); }
#Banner QPushButton {
    background: rgba(53,208,186,60);
    border: 1px solid rgba(53,208,186,160);
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 11px;
}
#Banner QPushButton:hover { background: rgba(53,208,186,95); }
QLabel#hint { color: rgba(234,247,247,170); font-size: 11px; }
QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,45); border-radius: 2px; }
QSlider::sub-page:horizontal { background: rgba(53,208,186,130); border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; background: #35d0ba;
}
"""


class MainWindow(QWidget):
    """无边框主窗口：TankWidget 铺满 + 悬浮芯片/控制栏/横幅。"""

    def __init__(self, connect: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("桌面鱼缸 · 鱼缸水生态系统模拟")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1120, 680)
        self.setMinimumSize(880, 560)

        self._connected = False  # notice 信号可能先于连接回调到达，必须先初始化

        self.client = BackendClient()
        self.client.state_changed.connect(self._on_state)
        self.client.connection_changed.connect(self._on_conn)
        self.client.notice.connect(self._on_notice)

        self.tank = TankWidget(self)
        self.chips = ChipBar(self)
        self.bar = ControlBar(self)
        self.bar.action.connect(self.client.call)
        self.bar.mode_requested.connect(self.tank.set_mode)
        self.tank.mode_changed.connect(self.bar.sync_mode)
        self.tank.mode_changed.connect(self._on_tank_mode)
        self.tank.tool_action.connect(self.client.call)

        self.btnMin = QPushButton("—", self)
        self.btnMin.setObjectName("winbtn")
        self.btnMin.setCursor(Qt.PointingHandCursor)
        self.btnMin.clicked.connect(self.showMinimized)
        self.btnClose = QPushButton("✕", self)
        self.btnClose.setObjectName("winbtn")
        self.btnClose.setCursor(Qt.PointingHandCursor)
        self.btnClose.clicked.connect(self.close)

        self.banner = QFrame(self)
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(10)
        self.bannerLabel = QLabel("后台未连接 — 正在尝试自动启动…")
        self.bannerLabel.setObjectName("hint")
        self.bannerBtn = QPushButton("重试启动后台")
        self.bannerBtn.setCursor(Qt.PointingHandCursor)
        self.bannerBtn.clicked.connect(lambda: self.client.request_reconnect(True))
        bl.addWidget(self.bannerLabel)
        bl.addWidget(self.bannerBtn)
        self.banner.hide()

        # 工具模式提示条（喂食/捞鱼时显示在控制栏上方）
        self.modeHint = QLabel("", self)
        self.modeHint.setObjectName("ModeHint")
        self.modeHint.hide()

        if connect:
            self.client.start()

    # ---------------- 状态接线 ----------------
    def _on_state(self, s: dict) -> None:
        self.tank.set_state(s)
        self.chips.update_state(s)
        self.bar.update_state(s)

    def _on_conn(self, ok: bool) -> None:
        self._connected = ok
        self.chips.set_connected(ok)
        if ok:
            self.banner.hide()
        else:
            self.bannerLabel.setText("后台未连接 — 正在尝试自动启动…")
            self.banner.show()
            self.banner.raise_()

    def _on_notice(self, text: str) -> None:
        self.bannerLabel.setText(text)
        if not self._connected:
            self.banner.show()
            self.banner.raise_()

    def _on_tank_mode(self, mode: str) -> None:
        """工具模式变化：同步提示条文案与位置。"""
        if mode == "feed":
            self.modeHint.setText("🍚 喂食模式 — 单击水面掉落鱼食 · 右键退出")
        elif mode == "net":
            self.modeHint.setText("🥅 捞鱼模式 — 点击/拖动捞走翻白肚的死鱼 · 右键退出")
        else:
            self.modeHint.hide()
            return
        self.modeHint.adjustSize()
        self.modeHint.move((self.width() - self.modeHint.width()) // 2,
                           self.height() - 118)
        self.modeHint.show()
        self.modeHint.raise_()

    # ---------------- 布局 ----------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        self.tank.setGeometry(0, 0, w, h)
        bar_w = min(940, w - 28)
        bar_h = 62
        self.bar.setGeometry((w - bar_w) // 2, h - bar_h - 12, bar_w, bar_h)
        self.chips.adjustSize()
        self.chips.move(12, 44)
        self.btnClose.setGeometry(w - 40, 12, 28, 22)
        self.btnMin.setGeometry(w - 74, 12, 28, 22)
        self.banner.adjustSize()
        self.banner.move((w - self.banner.width()) // 2, h - 118)
        if self.modeHint.isVisible():
            self.modeHint.adjustSize()
            self.modeHint.move((w - self.modeHint.width()) // 2, h - 118)
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.client.stop()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setApplicationName("桌面鱼缸")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
