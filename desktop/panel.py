"""悬浮 UI：顶部状态芯片栏 + 底部控制栏（含“更多”弹出面板）。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .metrics import clarity_color, clarity_label, clarity_of, health_color


class ChipBar(QWidget):
    """左上角半透明状态芯片组。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QVBoxLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._labels: dict[str, QLabel] = {}

        rows = [
            [("conn", "● 未连接"), ("temp", "🌡 --"), ("ph", "pH --"), ("oxy", "💧 O₂ --"), ("food", "🍚 食 --")],
            [("nh3", "氨氮 --"), ("no2", "亚硝 --"), ("no3", "硝酸 --"), ("clarity", "清澈 --"), ("health", "❤ 健康 --")],
            [("time", "⏱ --"), ("fish", "🐟 --"), ("plants", "🌿 --"), ("bact", "🦠 --"), ("water", "💧 --")],
        ]
        for row in rows:
            line = QWidget(self)
            lay = QHBoxLayout(line)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            for key, text in row:
                lab = QLabel(text)
                lab.setObjectName("chip")
                self._labels[key] = lab
                lay.addWidget(lab)
            lay.addStretch(1)
            grid.addWidget(line)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _set(self, key: str, text: str) -> None:
        self._labels[key].setText(text)

    def set_connected(self, ok: bool) -> None:
        lab = self._labels["conn"]
        lab.setText("● 已连接后台" if ok else "● 未连接")
        lab.setStyleSheet("color: #6ee7b7; font-weight: 600;" if ok else "color: #fda4af; font-weight: 600;")

    def update_state(self, s: dict) -> None:
        setv = self._set
        setv("temp", f"🌡 {float(s.get('temp', 0) or 0):.1f}℃")
        setv("ph", f"pH {float(s.get('ph', 0) or 0):.2f}")
        setv("oxy", f"💧 O₂ {float(s.get('oxygen', 0) or 0):.1f}")
        setv("food", f"🍚 食 {float(s.get('food', 0) or 0):.2f}")
        setv("nh3", f"氨氮 {float(s.get('ammonia', 0) or 0):.3f}")
        setv("no2", f"亚硝 {float(s.get('nitrite', 0) or 0):.3f}")
        setv("no3", f"硝酸 {float(s.get('nitrate', 0) or 0):.1f}")

        cl = clarity_of(s)
        setv("clarity", f"清澈 {cl * 100:.0f}% {clarity_label(cl)}")
        self._labels["clarity"].setStyleSheet(f"color: {clarity_color(cl)}; font-weight: 600;")

        hp = int(s.get("health", 0) or 0)
        setv("health", f"❤ 健康 {hp}")
        self._labels["health"].setStyleSheet(f"color: {health_color(hp)}; font-weight: 600;")

        t = float(s.get("time", 0) or 0)
        setv("time", f"⏱ 第{int(t // 24)}天{int(t % 24)}时")
        setv("fish", f"🐟 {int(s.get('fish', 0) or 0)}")
        setv("plants", f"🌿 {int(s.get('plants', 0) or 0)}")
        setv("bact", f"🦠 {float(s.get('bacteria', 0) or 0):.0f}")
        setv("water", f"💧 {float(s.get('water_volume', 0) or 0):.0f}L/容{int(s.get('capacity', 0) or 0)}")


class ControlBar(QWidget):
    """底部悬浮控制栏；`action` 信号把控制动作发给 BackendClient，
    `mode_requested` 把工具模式（feed/net/""）发给 TankWidget。"""

    action = Signal(str, object)
    mode_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlBar")
        self._state: dict[str, Any] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        def pill(text: str, checkable: bool = False) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("pill")
            b.setCursor(Qt.PointingHandCursor)
            if checkable:
                b.setCheckable(True)
            lay.addWidget(b)
            return b

        self.btnFeed = pill("🍚 喂食", checkable=True)
        self.btnFeed.setToolTip("进入喂食模式：光标变为鱼食，点击水面掉落鱼食；右键退出")
        self.btnFeed.toggled.connect(self._feed_toggled)
        self.btnPlant = pill("🌿 水草")
        self.btnPlant.clicked.connect(lambda: self.action.emit("add-plants", 1))
        self.btnFish = pill("🐟 加鱼")
        self.btnFish.clicked.connect(lambda: self.action.emit("add-fish", 1))
        self.btnWater = pill("💧 加水")
        self.btnWater.clicked.connect(lambda: self.action.emit("add-water", 10))
        self.btnBact = pill("🦠 细菌")
        self.btnBact.clicked.connect(lambda: self.action.emit("add-bacteria", 5))

        lay.addStretch(1)

        self.btnLight = pill("💡 灯光", checkable=True)
        self.btnLight.toggled.connect(lambda on: self.action.emit("light", bool(on)))
        self.btnFilter = pill("🌀 过滤", checkable=True)
        self.btnFilter.toggled.connect(lambda on: self.action.emit("filter", bool(on)))
        self.btnNet = pill("🥅 渔网", checkable=True)
        self.btnNet.setToolTip("进入捞鱼模式：点击或拖动渔网捞走翻白肚的死鱼；右键退出")
        self.btnNet.toggled.connect(self._net_toggled)
        self.btnMore = pill("⚙ 更多")
        self.btnMore.clicked.connect(self._toggle_pop)

        self._build_popover()

    # ---------------- 工具模式 ----------------
    def _feed_toggled(self, on: bool) -> None:
        if on:
            self._set_checked(self.btnNet, False)
            self.mode_requested.emit("feed")
        else:
            self.mode_requested.emit("")

    def _net_toggled(self, on: bool) -> None:
        if on:
            self._set_checked(self.btnFeed, False)
            self.mode_requested.emit("net")
        else:
            self.mode_requested.emit("")

    @staticmethod
    def _set_checked(btn: QPushButton, checked: bool) -> None:
        btn.blockSignals(True)
        btn.setChecked(checked)
        btn.blockSignals(False)

    def sync_mode(self, mode: str) -> None:
        """由 TankWidget.mode_changed 驱动（含右键取消），同步按钮选中态。"""
        self._set_checked(self.btnFeed, mode == "feed")
        self._set_checked(self.btnNet, mode == "net")

    # ---------------- 弹出面板 ----------------
    def _build_popover(self) -> None:
        self.pop = QFrame(self)
        self.pop.setObjectName("Popover")
        self.pop.hide()
        v = QVBoxLayout(self.pop)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        self.btnPause = QPushButton("⏸ 暂停")
        self.btnPause.setObjectName("pill")
        self.btnPause.clicked.connect(self._toggle_pause)
        v.addWidget(self.btnPause)

        self.lbSpeed = QLabel("速度 ×1.0")
        self.lbSpeed.setObjectName("hint")
        self.slSpeed = QSlider(Qt.Horizontal)
        self.slSpeed.setRange(1, 100)
        self.slSpeed.valueChanged.connect(lambda val: self.lbSpeed.setText(f"速度 ×{val / 10.0:.1f}"))
        self.slSpeed.sliderReleased.connect(lambda: self.action.emit("speed", self.slSpeed.value() / 10.0))
        v.addWidget(self._row(QLabel("速度"), self.slSpeed, self.lbSpeed))

        self.btnConst = QPushButton("恒温")
        self.btnConst.setObjectName("pill")
        self.btnConst.setCheckable(True)
        self.btnConst.clicked.connect(lambda: self.action.emit("temp-mode", "constant"))
        self.btnDay = QPushButton("昼夜")
        self.btnDay.setObjectName("pill")
        self.btnDay.setCheckable(True)
        self.btnDay.clicked.connect(lambda: self.action.emit("temp-mode", "daynight"))
        v.addWidget(self._row(QLabel("温度模式"), self.btnConst, self.btnDay))

        self.lbTemp = QLabel("目标 26℃")
        self.slTemp = QSlider(Qt.Horizontal)
        self.slTemp.setRange(16, 32)
        self.slTemp.valueChanged.connect(lambda val: self.lbTemp.setText(f"目标 {val}℃"))
        self.slTemp.sliderReleased.connect(lambda: self.action.emit("temp-set", self.slTemp.value()))
        v.addWidget(self._row(QLabel("目标温度"), self.slTemp, self.lbTemp))

        self.lbTmin = QLabel("夜温 24℃")
        self.slTmin = QSlider(Qt.Horizontal)
        self.slTmin.setRange(14, 30)
        self.slTmin.valueChanged.connect(lambda val: self.lbTmin.setText(f"夜温 {val}℃"))
        self.slTmin.sliderReleased.connect(lambda: self.action.emit("temp-min", self.slTmin.value()))
        v.addWidget(self._row(QLabel("昼夜·低温"), self.slTmin, self.lbTmin))

        self.lbTmax = QLabel("昼温 28℃")
        self.slTmax = QSlider(Qt.Horizontal)
        self.slTmax.setRange(20, 34)
        self.slTmax.valueChanged.connect(lambda val: self.lbTmax.setText(f"昼温 {val}℃"))
        self.slTmax.sliderReleased.connect(lambda: self.action.emit("temp-max", self.slTmax.value()))
        v.addWidget(self._row(QLabel("昼夜·高温"), self.slTmax, self.lbTmax))

        self.btnReset = QPushButton("🗑 重置鱼缸")
        self.btnReset.setObjectName("danger")
        self.btnReset.setCursor(Qt.PointingHandCursor)
        self.btnReset.clicked.connect(self._reset)
        v.addWidget(self.btnReset)

        self.pop.setFixedWidth(300)

    @staticmethod
    def _row(*items: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for it in items:
            h.addWidget(it)
        return w

    def _toggle_pop(self) -> None:
        if self.pop.isVisible():
            self.pop.hide()
            return
        self.pop.adjustSize()
        self.pop.move(self.width() - self.pop.width() - 6, -self.pop.height() - 10)
        self.pop.show()
        self.pop.raise_()

    def _toggle_pause(self) -> None:
        running = bool(self._state.get("running", True))
        self.action.emit("resume" if not running else "pause", None)

    def _reset(self) -> None:
        self.action.emit("reset", None)
        self.pop.hide()

    # ---------------- 状态同步 ----------------
    @staticmethod
    def _sync_slider(slider: QSlider, value: int) -> None:
        if slider.isSliderDown():
            return
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    def update_state(self, s: dict) -> None:
        self._state = s
        for btn, key in ((self.btnLight, "light"), (self.btnFilter, "filter_on")):
            btn.blockSignals(True)
            btn.setChecked(bool(s.get(key)))
            btn.blockSignals(False)

        running = bool(s.get("running", True))
        self.btnPause.setText("⏸ 暂停" if running else "▶ 继续")

        self._sync_slider(self.slSpeed, int(round(float(s.get("speed", 1) or 1) * 10)))
        self.lbSpeed.setText(f"速度 ×{float(s.get('speed', 1) or 1):.1f}")

        mode = s.get("temp_mode", "constant")
        for btn, m in ((self.btnConst, "constant"), (self.btnDay, "daynight")):
            btn.blockSignals(True)
            btn.setChecked(m == mode)
            btn.blockSignals(False)

        self._sync_slider(self.slTemp, int(round(float(s.get("temp_set", 26) or 26))))
        self.lbTemp.setText(f"目标 {self.slTemp.value()}℃")
        self._sync_slider(self.slTmin, int(round(float(s.get("temp_min", 24) or 24))))
        self.lbTmin.setText(f"夜温 {self.slTmin.value()}℃")
        self._sync_slider(self.slTmax, int(round(float(s.get("temp_max", 28) or 28))))
        self.lbTmax.setText(f"昼温 {self.slTmax.value()}℃")
