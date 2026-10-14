"""无边框鱼缸画面控件。

全部视觉元素在这里绘制与动画（30 FPS 定时器）：
- 鱼群：按后台鱼数/年龄结构生成，个体游动 + 摆尾，可被点击惊吓
- 死鱼：后台鱼数减少即判定死鱼，翻白肚漂上水面，可用渔网捞走
- 水草：簇状摆动，摆幅随水流强度变化
- 灯光：顶灯光柱 / 关灯变暗
- 过滤器：右上出水口冒泡 + 整体水流（流速线、颗粒漂移、鱼被水流推动）
- 水质清澈度：由氨氮/亚硝/硝酸/废物计算，水体颜色、浑浊雾团、漂浮颗粒
- 工具模式：喂食（光标变鱼食，点击水面掉食）/ 渔网（点击/拖动捞死鱼）
- 其他：水面波浪、食物颗粒下沉、点击涟漪、玻璃高光边框
"""
from __future__ import annotations

import math
import random
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from . import assets
from .metrics import clamp, clarity_of

SURFACE_Y = 46        # 水面高度（上方为空气层/灯）
GRAVEL_H = 30         # 底砂厚度
TICK_MS = 33          # 动画帧间隔
MAX_FISH = 34         # 同屏最多鱼的可见数（性能保护）
MAX_PLANTS = 16       # 同屏最多水草簇
MAX_SPECKS = 90       # 浑浊漂浮颗粒上限
FILTER_OFFSET = 140   # 过滤器出水管中心距右缘的距离（避开右上角窗口按钮）
RADIUS = 18           # 鱼缸圆角

FISH_PALETTE = [
    (255, 176, 84),    # 金橙
    (255, 214, 110),   # 金黄
    (120, 200, 255),   # 淡蓝
    (255, 130, 130),   # 红粉
    (235, 240, 225),   # 银白
    (170, 255, 210),   # 青绿
]
CLASS_SIZE = {0: 7.5, 1: 11.5, 2: 15.0}   # 幼鱼/成年/老年 半身长 px

_WATER_CLEAR = ((126, 208, 226), (52, 142, 176), (20, 84, 118))
_WATER_GREEN = ((150, 192, 140), (86, 138, 92), (44, 84, 56))
_WATER_BROWN = ((168, 158, 122), (112, 102, 72), (58, 52, 38))
_GREENS = [(52, 150, 84), (70, 176, 98), (40, 124, 68)]
_PEBBLE_COLORS = [(188, 168, 128), (150, 132, 96), (206, 190, 150), (120, 104, 76)]


def _mix(c1: tuple, c2: tuple, t: float) -> tuple:
    """线性混合两个 RGB 颜色。"""
    t = clamp(t, 0.0, 1.0)
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def _scale(c: tuple, f: float) -> tuple:
    return tuple(int(v * f) for v in c)


_GREENS_DARK = [_scale(g, 0.55) for g in _GREENS]   # 水草底层描边色


def _make_feed_cursor() -> tuple[QPixmap, tuple[int, int]]:
    """鱼食光标：一小撮褐色颗粒，热点在颗粒中心（下落点）。支持贴图替换。"""
    pm = assets.get("feed_cursor")
    if pm is not None:
        if pm.width() > 64 or pm.height() > 64:
            pm = pm.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pm, (pm.width() // 2, pm.height() // 2)
    pm = QPixmap(34, 34)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(214, 178, 96))
    for x, y, r in ((13, 11, 3.2), (20, 12, 2.8), (15, 18, 3.0), (22, 18, 2.6)):
        p.drawEllipse(QPointF(x, y), r, r)
    p.setBrush(QColor(170, 130, 60))
    p.drawEllipse(QPointF(17, 24), 2.4, 2.4)
    p.end()
    return pm, (17, 22)


def _make_net_cursor() -> tuple[QPixmap, tuple[int, int]]:
    """渔网光标：网圈 + 网格 + 手柄，热点在网圈中心（捞取点）。支持贴图替换。"""
    pm = assets.get("net")
    if pm is not None:
        if pm.width() > 64 or pm.height() > 64:
            pm = pm.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pm, (pm.width() // 2, pm.height() // 2)
    pm = QPixmap(34, 34)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(150, 110, 70), 3))
    p.drawLine(QPointF(17, 17), QPointF(29, 29))
    p.setPen(QPen(QColor(240, 245, 250, 230), 2))
    p.setBrush(QColor(240, 245, 250, 40))
    p.drawEllipse(QPointF(11, 11), 8, 8)
    p.setPen(QPen(QColor(240, 245, 250, 140), 1))
    for d in (-4, 0, 4):
        half = math.sqrt(max(64.0 - d * d, 4.0))
        p.drawLine(QPointF(11 + d, 11 - half), QPointF(11 + d, 11 + half))
        p.drawLine(QPointF(11 - half, 11 + d), QPointF(11 + half, 11 + d))
    p.end()
    return pm, (11, 11)


def _water_colors(clarity: float) -> list[tuple]:
    """按清澈度返回水体 渐变三色：清→绿藻→褐浊。"""
    if clarity >= 0.6:
        t = (clarity - 0.6) / 0.4
        return [_mix(g, c, t) for g, c in zip(_WATER_GREEN, _WATER_CLEAR)]
    t = clarity / 0.6
    return [_mix(b, g, t) for b, g in zip(_WATER_BROWN, _WATER_GREEN)]


class _Fish:
    __slots__ = ("x", "y", "vx", "vy", "phase", "cls", "color", "sprite")

    def __init__(self, x: float, y: float, cls: int, color: tuple,
                 sprite: str | None = None) -> None:
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.phase = random.uniform(0.0, math.tau)
        self.cls = cls
        self.color = color
        self.sprite = sprite


class TankWidget(QWidget):
    """鱼缸本体：负责所有绘制与本地动画，状态由 `set_state` 注入。"""

    mode_changed = Signal(str)      # 工具模式变化（""/feed/net，含右键取消）
    tool_action = Signal(str, object)  # 工具触发的后台动作（如掉食 → feed）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._state: dict[str, Any] = {}
        self._rng = random.Random(20240601)   # 布局种子（底砂/雾团位置固定）

        self._t = 0.0
        self._clarity = 1.0
        self._flow = 0.3
        self._filter_on = False
        self._light_on = True
        self._food_level = 0.0

        self._fish: list[_Fish] = []
        self._class_targets = (0, 0, 0)
        self._plants: list[dict] = []
        self._target_plants = 0
        self._bubbles: list[dict] = []
        self._food: list[dict] = []
        self._specks: list[dict] = []
        self._ripples: list[dict] = []
        self._pebbles: list[dict] = []
        self._blobs: list[dict] = []
        self._bubble_clock = 0.0
        self._drag_active = False
        self._drag_offset = QPoint()
        self._resize_edges: Qt.Edges = Qt.Edges()
        self._press_global = QPoint()
        self._press_geom = QRect()

        # 工具模式（feed 喂食 / net 渔网 / "" 无）与死鱼
        self._mode = ""
        self._net_dragging = False
        self._corpses: list[dict] = []
        self._drops: list[dict] = []
        self._last_total: int | None = None
        self._last_time = 0.0
        self._pm_feed, self._feed_hot = _make_feed_cursor()
        self._pm_net, self._net_hot = _make_net_cursor()
        self._fish_sprites = self._load_fish_sprites()

        self._make_static_layout()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------- 状态注入 ----------------
    def set_state(self, s: dict) -> None:
        """接收后台快照（主线程信号调用）。"""
        prev_total, prev_time = self._last_total, self._last_time
        self._state = s
        total = int(s.get("fish", 0) or 0)
        now_t = float(s.get("time", 0) or 0)
        is_reset = prev_total is not None and now_t + 0.01 < prev_time
        if is_reset:
            self._corpses.clear()
            self._fish.clear()

        # 年龄结构目标（幼鱼/成年/老年，按可见上限截断）
        age = s.get("fish_age") or {}
        total_c = min(total, MAX_FISH)
        young_t = min(int(age.get("young", 0) or 0), total_c)
        senior_t = min(int(age.get("senior", 0) or 0), max(total_c - young_t, 0))
        adult_t = max(total_c - young_t - senior_t, 0)

        # 死鱼判定：后台鱼只会因死亡减少；按年龄结构的减少量把对应鱼变成尸体
        if prev_total is not None and not is_reset:
            counts = [0, 0, 0]
            for f in self._fish:
                counts[f.cls] += 1
            for cls, target in enumerate((young_t, adult_t, senior_t)):
                for _ in range(max(counts[cls] - target, 0)):
                    self._kill_fish_of_class(cls)

        self._last_total = total
        self._last_time = now_t
        self._class_targets = (young_t, adult_t, senior_t)
        self._target_plants = min(int(s.get("plants", 0) or 0), MAX_PLANTS)
        self._food_level = clamp(float(s.get("food", 0) or 0), 0.0, 6.0)
        self._filter_on = bool(s.get("filter_on"))
        self._light_on = bool(s.get("light", True))

    # ---------------- 布局种子 ----------------
    def _make_static_layout(self) -> None:
        rng = self._rng
        self._pebbles = [
            {
                "u": rng.random(),
                "ry": rng.uniform(0.15, 0.92),
                "r": rng.uniform(1.5, 4.6),
                "c": _PEBBLE_COLORS[rng.randrange(len(_PEBBLE_COLORS))],
            }
            for _ in range(90)
        ]
        self._blobs = [
            {
                "u": rng.random(),
                "v": rng.uniform(0.05, 0.85),
                "r": rng.uniform(55, 120),
                "ph": rng.uniform(0.0, math.tau),
            }
            for _ in range(5)
        ]

    def _sync_plants(self) -> None:
        while len(self._plants) < self._target_plants:
            blades = [
                {
                    "du": self._rng.uniform(-9.0, 9.0),
                    "h": self._rng.uniform(34.0, 110.0),
                    "w": self._rng.uniform(1.8, 3.2),
                    "ph": self._rng.uniform(0.0, math.tau),
                    "ci": self._rng.randrange(3),
                }
                for _ in range(self._rng.randint(3, 6))
            ]
            self._plants.append({"u": self._rng.uniform(0.05, 0.95), "blades": blades})
        while len(self._plants) > self._target_plants:
            self._plants.pop()

    def _load_fish_sprites(self) -> list[str]:
        """收集可用的鱼贴图：fish.png（淡染多色）+ fish_0..5.png（原色）。"""
        names = []
        if assets.has("fish"):
            names.append("fish")
        for i in range(6):
            n = f"fish_{i}"
            if assets.has(n):
                names.append(n)
        return names

    def _spawn_fish(self, cls: int, w: int, h: int) -> _Fish:
        from_left = random.random() < 0.5
        f = _Fish(
            x=-18.0 if from_left else w + 18.0,
            y=random.uniform(SURFACE_Y + 30.0, max(SURFACE_Y + 40.0, h - GRAVEL_H - 50.0)),
            cls=cls,
            color=random.choice(FISH_PALETTE),
            sprite=random.choice(self._fish_sprites) if self._fish_sprites else None,
        )
        f.vx = random.uniform(20.0, 45.0) * (1.0 if from_left else -1.0)
        f.vy = random.uniform(-8.0, 8.0)
        return f

    def _sync_fish(self, w: int, h: int) -> None:
        counts = [0, 0, 0]
        for f in self._fish:
            counts[f.cls] += 1
        for cls in range(3):
            for _ in range(min(self._class_targets[cls] - counts[cls], 2)):
                self._fish.append(self._spawn_fish(cls, w, h))
                counts[cls] += 1
        surplus = [(counts[c] - self._class_targets[c], c) for c in range(3)]
        while len(self._fish) > sum(self._class_targets) and max(surplus)[0] > 0:
            _, cls = max(surplus)
            idx = next(i for i, f in enumerate(self._fish) if f.cls == cls)
            del self._fish[idx]
            counts[cls] -= 1
            surplus = [(counts[c] - self._class_targets[c], c) for c in range(3)]

    # ---------------- 工具模式（喂食 / 渔网） ----------------
    def set_mode(self, mode: str) -> None:
        mode = mode if mode in ("feed", "net") else ""
        if mode != self._mode:
            self._mode = mode
            self._apply_cursor()
            self.mode_changed.emit(mode)

    def _apply_cursor(self) -> None:
        if self._mode == "feed":
            self.setCursor(QCursor(self._pm_feed, *self._feed_hot))
        elif self._mode == "net":
            self.setCursor(QCursor(self._pm_net, *self._net_hot))
        else:
            self.unsetCursor()

    def _drop_food(self, x: float, y: float) -> None:
        """在指针处掉落一小撮鱼食，并通知后台 feed。"""
        for _ in range(random.randint(4, 7)):
            self._food.append({
                "x": x + random.uniform(-7.0, 7.0),
                "y": y + random.uniform(-4.0, 4.0),
                "vy": random.uniform(14.0, 30.0),
                "r": random.uniform(1.2, 2.4),
                "life": 1.0,
            })
        if len(self._food) > 120:
            del self._food[: len(self._food) - 120]
        self._ripples.append({"x": x, "y": y, "r": 5.0})
        self.tool_action.emit("feed", 0.3)

    def _scoop_at(self, x: float, y: float) -> int:
        """捞走半径内的死鱼，返回捞到的数量。"""
        kept, scooped = [], 0
        for c in self._corpses:
            if math.hypot(c["x"] - x, c["y"] - y) <= 42.0:
                scooped += 1
            else:
                kept.append(c)
        if scooped:
            self._corpses = kept
            self._ripples.append({"x": x, "y": y, "r": 8.0})
            for _ in range(6 * min(scooped, 3)):
                self._drops.append({
                    "x": x + random.uniform(-8.0, 8.0),
                    "y": y + random.uniform(-6.0, 2.0),
                    "vx": random.uniform(-36.0, 36.0),
                    "vy": random.uniform(-130.0, -60.0),
                    "r": random.uniform(1.2, 2.4),
                    "life": 1.0,
                })
            if len(self._drops) > 80:
                del self._drops[: len(self._drops) - 80]
        return scooped

    def _kill_fish_of_class(self, cls: int) -> None:
        """把一条指定类别的活鱼变成翻白肚的尸体。"""
        idxs = [i for i, f in enumerate(self._fish) if f.cls == cls]
        if not idxs:
            return
        f = self._fish.pop(random.choice(idxs))
        self._corpses.append({
            "x": f.x,
            "y": f.y,
            "cls": f.cls,
            "color": f.color,
            "sprite": f.sprite,
            "flip": f.vx < 0.0,
            "rot": random.uniform(-14.0, 14.0),
            "ph": random.uniform(0.0, math.tau),
        })

    # ---------------- 动画推进 ----------------
    def _tick(self) -> None:
        dt = TICK_MS / 1000.0
        self._t += dt
        w, h = self.width(), self.height()
        if w < 60 or h < 60:
            return

        target_clarity = clarity_of(self._state) if self._state else 1.0
        self._clarity += (target_clarity - self._clarity) * min(1.0, 3.0 * dt)
        flow_target = 1.0 if self._filter_on else 0.3
        self._flow += (flow_target - self._flow) * min(1.0, 1.5 * dt)

        self._sync_plants()
        self._sync_fish(w, h)
        self._advance_fish(dt, w, h)
        self._advance_corpses(dt, w)
        self._advance_drops(dt)
        self._advance_bubbles(dt, w, h)
        self._advance_food(dt, w, h)
        self._advance_specks(dt, w, h)
        for rp in self._ripples:
            rp["r"] += 55.0 * dt
        self._ripples = [rp for rp in self._ripples if rp["r"] < 150.0]

        self.update()

    def _advance_fish(self, dt: float, w: int, h: int) -> None:
        top = SURFACE_Y + 24.0
        bottom = h - GRAVEL_H - 34.0
        flow_push = -55.0 * self._flow      # 过滤器水流向左
        for f in self._fish:
            f.phase += dt * (4.0 + abs(f.vx) * 0.05)
            f.vx += random.uniform(-40.0, 40.0) * dt
            f.vy += random.uniform(-24.0, 24.0) * dt
            f.vx += flow_push * dt
            margin = 36.0
            if f.x < margin:
                f.vx += 130.0 * dt
            if f.x > w - margin:
                f.vx -= 130.0 * dt
            if f.y < top:
                f.vy += 130.0 * dt
            if f.y > bottom:
                f.vy -= 130.0 * dt
            speed = math.hypot(f.vx, f.vy)
            max_sp = 80.0 if f.cls == 0 else 60.0
            if speed > max_sp:
                k = max_sp / speed
                f.vx *= k
                f.vy *= k
            elif speed < 14.0 and speed > 0.01:
                k = 14.0 / speed
                f.vx *= k
                f.vy *= k
            f.x += f.vx * dt
            f.y += f.vy * dt

    def _advance_corpses(self, dt: float, w: int) -> None:
        """死鱼缓慢上浮到水面并随水流漂移，贴壁堆积。"""
        surf = SURFACE_Y + 8.0
        for c in self._corpses:
            if c["y"] > surf + 2.0:
                c["y"] = max(surf + 2.0, c["y"] - 34.0 * dt)
            c["x"] -= (self._flow * 26.0 + 4.0) * dt
            c["x"] = clamp(c["x"], 40.0, w - 40.0)
        if len(self._corpses) > 24:
            del self._corpses[: len(self._corpses) - 24]

    def _advance_drops(self, dt: float) -> None:
        """渔网捞起时的水珠抛物线。"""
        for d in self._drops:
            d["vy"] += 420.0 * dt
            d["x"] += d["vx"] * dt
            d["y"] += d["vy"] * dt
            d["life"] -= dt * 1.4
        self._drops = [d for d in self._drops if d["life"] > 0.0]

    def _advance_bubbles(self, dt: float, w: int, h: int) -> None:
        surface = SURFACE_Y + 8.0
        self._bubble_clock += dt
        if self._filter_on:
            if self._bubble_clock > 0.13:
                self._bubble_clock = 0.0
                self._bubbles.append({
                    "x": w - FILTER_OFFSET + random.uniform(-5.0, 5.0),
                    "y": SURFACE_Y + 52.0,
                    "r": random.uniform(1.5, 3.4),
                    "ph": random.uniform(0.0, math.tau),
                })
        elif random.random() < dt * 0.8:
            self._bubbles.append({
                "x": random.uniform(30.0, w - 30.0),
                "y": h - GRAVEL_H - 4.0,
                "r": random.uniform(1.0, 2.2),
                "ph": random.uniform(0.0, math.tau),
            })
        for b in self._bubbles:
            b["y"] -= (26.0 + b["r"] * 9.0) * dt
            b["x"] += (math.sin(self._t * 3.0 + b["ph"]) * 9.0 - 26.0 * self._flow) * dt
        self._bubbles = [b for b in self._bubbles if b["y"] > surface]

    def _advance_food(self, dt: float, w: int, h: int) -> None:
        want = min(int(self._food_level * 9.0), 46)
        if len(self._food) < want and random.random() < dt * 9.0:
            self._food.append({
                "x": random.uniform(40.0, w - 40.0),
                "y": SURFACE_Y + 4.0,
                "vy": random.uniform(14.0, 30.0),
                "r": random.uniform(1.2, 2.4),
                "life": 1.0,
            })
        ground = h - GRAVEL_H + 2.0
        for g in self._food:
            if g["y"] < ground:
                g["y"] += g["vy"] * dt
            else:
                g["life"] -= dt * 0.25
        self._food = [g for g in self._food if g["life"] > 0.0]

    def _advance_specks(self, dt: float, w: int, h: int) -> None:
        murk = 1.0 - self._clarity
        want = int(MAX_SPECKS * murk)
        while len(self._specks) < want:
            self._specks.append({
                "x": random.random(),
                "y": random.random(),
                "r": random.uniform(0.8, 2.6),
                "ph": random.uniform(0.0, math.tau),
            })
        if len(self._specks) > want:
            self._specks = self._specks[:want]
        drift = -(self._flow * 30.0 + 4.0) * dt / max(w, 1)
        for s in self._specks:
            s["x"] = (s["x"] + drift + math.sin(self._t * 0.8 + s["ph"]) * 0.002) % 1.0
            s["y"] = (s["y"] + math.cos(self._t * 0.5 + s["ph"]) * 0.0018) % 1.0

    # ---------------- 绘制 ----------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        clip = QPainterPath()
        clip.addRoundedRect(0.0, 0.0, float(w), float(h), RADIUS, RADIUS)
        p.setClipPath(clip)

        self._paint_air(p, w, h)
        self._paint_water(p, w, h)
        self._paint_beams(p, w, h)
        self._paint_flow_lines(p, w, h)
        self._paint_gravel(p, w, h)
        self._paint_plants(p, w, h)
        self._paint_food(p)
        self._paint_fish(p)
        self._paint_corpses(p)
        self._paint_bubbles(p)
        self._paint_murk(p, w, h)
        self._paint_surface(p, w, h)
        self._paint_drops(p)
        if not self._light_on:
            p.fillRect(QRectF(0, SURFACE_Y, w, h - SURFACE_Y), QColor(6, 12, 18, 70))
        self._paint_ripples(p)
        self._paint_glass(p, w, h)
        p.end()

    def _paint_air(self, p: QPainter, w: int, h: int) -> None:
        """上方空气层 + 顶灯 + 过滤器。"""
        grad = QLinearGradient(0, 0, 0, SURFACE_Y)
        grad.setColorAt(0.0, QColor(34, 44, 54))
        grad.setColorAt(1.0, QColor(20, 27, 34))
        p.fillRect(QRectF(0, 0, w, SURFACE_Y), grad)

        # 顶灯：灯罩 + 灯管 + 辉光
        lamp_w = w * 0.56
        cx = w / 2.0
        housing = QRectF(cx - lamp_w / 2.0 - 7.0, 8.0, lamp_w + 14.0, 15.0)
        p.setPen(QPen(QColor(255, 255, 255, 42), 1))
        p.setBrush(QColor(16, 22, 28, 235))
        p.drawRoundedRect(housing, 7, 7)
        p.setPen(Qt.NoPen)
        lamp = QRectF(cx - lamp_w / 2.0, 11.0, lamp_w, 9.0)
        if self._light_on:
            glow = QRadialGradient(lamp.center(), lamp_w * 0.42)
            glow.setColorAt(0.0, QColor(255, 250, 220, 120))
            glow.setColorAt(1.0, QColor(255, 250, 220, 0))
            p.setBrush(QColor(255, 248, 214, 245))
            p.drawRoundedRect(lamp, 4, 4)
            p.fillRect(QRectF(0, 0, w, SURFACE_Y + 6), glow)
        else:
            p.setBrush(QColor(120, 130, 140, 90))
            p.drawRoundedRect(lamp, 4, 4)

        # 过滤器（右上，位于窗口按钮左侧，避免重叠）
        box = QRectF(w - 172, 12, 68, 22)
        p.setBrush(QColor(28, 34, 40, 235))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        for i in range(4):
            x = box.x() + 9 + i * 11
            p.drawLine(QPointF(x, box.y() + 5), QPointF(x, box.y() + box.height() - 5))
        dot_pos = QPointF(box.right() - 12, box.center().y())
        dot_c = QColor(53, 208, 186) if self._filter_on else QColor(90, 96, 104)
        p.setPen(Qt.NoPen)
        p.setBrush(dot_c)
        p.drawEllipse(dot_pos, 3.0, 3.0)
        if self._filter_on:
            glow = QRadialGradient(dot_pos, 12)
            glow.setColorAt(0.0, QColor(53, 208, 186, 120))
            glow.setColorAt(1.0, QColor(53, 208, 186, 0))
            p.setBrush(glow)
            p.drawEllipse(dot_pos, 12.0, 12.0)

    def _paint_water(self, p: QPainter, w: int, h: int) -> None:
        c_top, c_mid, c_bot = _water_colors(self._clarity)
        grad = QLinearGradient(0, SURFACE_Y, 0, h)
        grad.setColorAt(0.0, QColor(*c_top))
        grad.setColorAt(0.45, QColor(*c_mid))
        grad.setColorAt(1.0, QColor(*c_bot))
        p.fillRect(QRectF(0, SURFACE_Y, w, h - SURFACE_Y), grad)
        # 出水管伸入水中（在水体之后绘制才不会被盖住；气泡从管口下方冒出）
        p.setBrush(QColor(40, 48, 56))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(w - FILTER_OFFSET - 6, 32, 12, 62))

    def _paint_beams(self, p: QPainter, w: int, h: int) -> None:
        """开灯时的光柱。"""
        if not self._light_on:
            return
        top = float(SURFACE_Y + 2)
        bottom = SURFACE_Y + (h - SURFACE_Y) * 0.62
        for i in range(3):
            cx = w * (0.26 + 0.24 * i) + math.sin(self._t * 0.22 + i * 1.9) * 26.0
            path = QPainterPath()
            path.moveTo(cx - 14, top)
            path.lineTo(cx + 14, top)
            path.lineTo(cx + 62, bottom)
            path.lineTo(cx - 62, bottom)
            path.closeSubpath()
            g = QLinearGradient(0, top, 0, bottom)
            g.setColorAt(0.0, QColor(255, 252, 230, 40))
            g.setColorAt(1.0, QColor(255, 252, 230, 0))
            p.fillPath(path, g)

    def _paint_flow_lines(self, p: QPainter, w: int, h: int) -> None:
        """水流流速线（过滤器开时更明显）。"""
        flow = self._flow
        if flow < 0.14:
            return
        pen = p.pen()
        pen.setWidthF(1.3)
        alpha = int(14 + 34 * flow)
        for i in range(3):
            y0 = SURFACE_Y + 70 + i * 84
            if y0 > h - GRAVEL_H - 20:
                break
            pen.setColor(QColor(255, 255, 255, alpha))
            p.setPen(pen)
            path = QPainterPath()
            amp = 5.0 + 2.5 * i
            speed = 40.0 + 30.0 * i
            for x in range(0, w + 16, 16):
                y = y0 + math.sin((x + self._t * speed * flow) * 0.02 + i * 2.1) * amp
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.drawPath(path)

    def _paint_gravel(self, p: QPainter, w: int, h: int) -> None:
        ground_y = h - GRAVEL_H
        grad = QLinearGradient(0, ground_y, 0, h)
        grad.setColorAt(0.0, QColor(96, 84, 62))
        grad.setColorAt(1.0, QColor(52, 46, 34))
        p.fillRect(QRectF(0, ground_y, w, GRAVEL_H), grad)
        p.setPen(Qt.NoPen)
        for peb in self._pebbles:
            x = peb["u"] * w
            y = ground_y + peb["ry"] * GRAVEL_H
            p.setBrush(QColor(*peb["c"]))
            p.drawEllipse(QPointF(x, y), peb["r"], peb["r"] * 0.8)
            # 左上高光 → 鹅卵石质感
            p.setBrush(QColor(*_mix(peb["c"], (255, 255, 255), 0.32)))
            p.drawEllipse(QPointF(x - peb["r"] * 0.24, y - peb["r"] * 0.26),
                          peb["r"] * 0.52, peb["r"] * 0.40)

    def _paint_plants(self, p: QPainter, w: int, h: int) -> None:
        ground = h - GRAVEL_H + 5.0
        amp = 3.0 + 13.0 * self._flow
        light_f = 1.0 if self._light_on else 0.72
        sprite = assets.get("plant")
        if sprite is not None:
            # 贴图模式：以根部为轴心旋转摇摆
            for cluster in self._plants:
                bx = cluster["u"] * w
                for b in cluster["blades"][:3]:
                    ang = (-self._flow * 5.0
                           + math.sin(self._t * 1.3 + b["ph"]) * (3.0 + 9.0 * self._flow))
                    th = b["h"] * 1.7
                    tw = th * sprite.width() / max(sprite.height(), 1)
                    p.save()
                    p.translate(bx + b["du"], ground)
                    p.rotate(ang)
                    p.setOpacity(light_f)
                    p.drawPixmap(QRectF(-tw / 2.0, -th, tw, th), sprite,
                                 QRectF(sprite.rect()))
                    p.setOpacity(1.0)
                    p.restore()
            return
        pen = p.pen()
        pen.setCapStyle(Qt.RoundCap)
        for cluster in self._plants:
            bx = cluster["u"] * w
            for b in cluster["blades"]:
                bend = (
                    math.sin(self._t * 1.3 + b["ph"]) * amp * (b["h"] / 90.0)
                    - self._flow * 7.0
                )
                path = QPainterPath(QPointF(bx + b["du"], ground))
                path.quadTo(
                    QPointF(bx + b["du"] + bend * 0.35, ground - b["h"] * 0.55),
                    QPointF(bx + b["du"] + bend, ground - b["h"]),
                )
                # 底层深色粗描边 + 上层亮色描边 → 立体感
                pen.setWidthF(b["w"] + 1.6)
                pen.setColor(QColor(*_scale(_GREENS_DARK[b["ci"]], light_f)))
                p.setPen(pen)
                p.drawPath(path)
                pen.setWidthF(b["w"])
                pen.setColor(QColor(*_scale(_GREENS[b["ci"]], light_f)))
                p.setPen(pen)
                p.drawPath(path)

    def _paint_food(self, p: QPainter) -> None:
        sprite = assets.get("food")
        p.setPen(Qt.NoPen)
        for g in self._food:
            life = clamp(g["life"], 0.0, 1.0)
            if sprite is not None:
                d = g["r"] * 5.0
                p.setOpacity(life)
                p.drawPixmap(QRectF(g["x"] - d / 2.0, g["y"] - d / 2.0, d, d), sprite,
                             QRectF(sprite.rect()))
                p.setOpacity(1.0)
            else:
                p.setBrush(QColor(214, 178, 96, int(220 * life)))
                p.drawEllipse(QPointF(g["x"], g["y"]), g["r"], g["r"])
                p.setBrush(QColor(255, 240, 190, int(120 * life)))
                p.drawEllipse(QPointF(g["x"] - g["r"] * 0.3, g["y"] - g["r"] * 0.35),
                              g["r"] * 0.32, g["r"] * 0.28)

    def _paint_fish(self, p: QPainter) -> None:
        for f in self._fish:
            s = CLASS_SIZE[f.cls]
            if f.sprite:
                # 贴图：fish.png 淡染配色；fish_N.png 原色
                sprite = (assets.get(f.sprite) if f.sprite != "fish"
                          else assets.tinted("fish", f.color, 0.32))
            else:
                sprite = None
            p.save()
            p.translate(f.x, f.y)
            if f.vx < 0:
                p.scale(-1.0, 1.0)
            if sprite is not None:
                tw = s * 3.1
                th = tw * sprite.height() / max(sprite.width(), 1)
                p.drawPixmap(QRectF(-tw / 2.0, -th / 2.0, tw, th), sprite,
                             QRectF(sprite.rect()))
            else:
                col = f.color
                wag = math.sin(f.phase) * 0.5
                # 尾鳍（双叶，随相位摆动）
                p.save()
                p.translate(-s * 0.95, 0.0)
                p.rotate(math.degrees(wag))
                tail = QPolygonF([
                    QPointF(0.0, 0.0),
                    QPointF(-s * 0.62, -s * 0.62),
                    QPointF(-s * 0.40, 0.0),
                    QPointF(-s * 0.62, s * 0.62),
                ])
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*_mix(col, (10, 16, 30), 0.30)))
                p.drawPolygon(tail)
                p.restore()
                # 身体（纺锤形，三段渐变 + 深色描边）
                body = QPainterPath()
                body.moveTo(s * 1.25, 0.0)
                body.cubicTo(s * 0.85, -s * 0.55, -s * 0.15, -s * 0.58, -s * 0.95, -s * 0.16)
                body.quadTo(-s * 1.12, 0.0, -s * 0.95, s * 0.16)
                body.cubicTo(-s * 0.15, s * 0.58, s * 0.85, s * 0.55, s * 1.25, 0.0)
                grad = QLinearGradient(0, -s * 0.55, 0, s * 0.55)
                grad.setColorAt(0.0, QColor(*_mix(col, (255, 255, 255), 0.45)))
                grad.setColorAt(0.55, QColor(*col))
                grad.setColorAt(1.0, QColor(*_mix(col, (0, 0, 40), 0.38)))
                p.setPen(QPen(QColor(*_mix(col, (0, 0, 30), 0.45)), max(0.8, s * 0.05)))
                p.setBrush(grad)
                p.drawPath(body)
                # 背鳍
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*_mix(col, (255, 255, 255), 0.15)))
                p.drawPolygon(QPolygonF([
                    QPointF(-s * 0.32, -s * 0.44),
                    QPointF(0.05 * s, -s * 0.66),
                    QPointF(0.28 * s, -s * 0.30),
                ]))
                # 胸鳍（小幅摆动）
                p.save()
                p.translate(s * 0.1, s * 0.16)
                p.rotate(math.degrees(wag * 0.6) + 18.0)
                p.setBrush(QColor(*_mix(col, (255, 255, 255), 0.10), 170))
                p.drawEllipse(QPointF(-s * 0.12, 0.0), s * 0.30, s * 0.12)
                p.restore()
                # 眼睛 + 高光
                p.setBrush(QColor(16, 18, 24))
                p.drawEllipse(QPointF(s * 0.74, -s * 0.08), s * 0.11, s * 0.11)
                p.setBrush(QColor(255, 255, 255, 210))
                p.drawEllipse(QPointF(s * 0.77, -s * 0.12), s * 0.035, s * 0.035)
            p.restore()

    def _paint_corpses(self, p: QPainter) -> None:
        """死鱼：翻白肚（垂直翻转）+ 苍白色 + X 眼，浮在水面轻微摇晃。"""
        corpse_pm = assets.get("corpse")
        for c in self._corpses:
            s = CLASS_SIZE[c["cls"]]
            yy = c["y"] + math.sin(self._t * 1.6 + c["ph"]) * 1.4
            rot = c["rot"] + math.sin(self._t * 0.7 + c["ph"]) * 5.0
            p.save()
            p.translate(c["x"], yy)
            p.rotate(rot)
            dir_x = -1.0 if c["flip"] else 1.0
            # 贴图优先级：corpse.png（本身已翻肚）> 淡白的鱼贴图 > 程序绘制
            if corpse_pm is not None:
                p.scale(dir_x, 1.0)
                tw = s * 3.1
                th = tw * corpse_pm.height() / max(corpse_pm.width(), 1)
                p.drawPixmap(QRectF(-tw / 2.0, -th / 2.0, tw, th), corpse_pm,
                             QRectF(corpse_pm.rect()))
            elif c.get("sprite"):
                pale = assets.tinted(c["sprite"], (248, 248, 242), 0.78)
                p.scale(dir_x, -1.0)
                if pale is not None:
                    tw = s * 3.1
                    th = tw * pale.height() / max(pale.width(), 1)
                    p.drawPixmap(QRectF(-tw / 2.0, -th / 2.0, tw, th), pale,
                                 QRectF(pale.rect()))
                else:
                    col = c["color"]
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(*_mix(col, (245, 245, 238), 0.72)))
                    p.drawEllipse(QPointF(0, 0), s * 1.15, s * 0.52)
            else:
                p.scale(dir_x, -1.0)
                col = c["color"]
                pale_top = _mix(col, (245, 245, 238), 0.72)
                pale_bot = _mix(col, (205, 205, 195), 0.45)
                # 尾鳍（不再摆动）
                p.save()
                p.translate(-s * 1.05, 0.0)
                tail = QPolygonF([
                    QPointF(0.0, 0.0),
                    QPointF(-s * 0.95, -s * 0.55),
                    QPointF(-s * 0.7, 0.0),
                    QPointF(-s * 0.95, s * 0.55),
                ])
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*_mix(pale_top, (170, 170, 165), 0.25)))
                p.drawPolygon(tail)
                p.restore()
                # 身体（翻肚后浅色朝上）
                body = QLinearGradient(0, s * 0.55, 0, -s * 0.55)
                body.setColorAt(0.0, QColor(*pale_bot))
                body.setColorAt(1.0, QColor(*pale_top))
                p.setBrush(body)
                p.drawEllipse(QPointF(0, 0), s * 1.15, s * 0.52)
                # X 眼
                ex, ey, er = s * 0.72, -s * 0.06, s * 0.16
                p.setPen(QPen(QColor(95, 95, 100), max(1.0, s * 0.09)))
                p.drawLine(QPointF(ex - er, ey - er), QPointF(ex + er, ey + er))
                p.drawLine(QPointF(ex - er, ey + er), QPointF(ex + er, ey - er))
            p.restore()

    def _paint_drops(self, p: QPainter) -> None:
        p.setPen(Qt.NoPen)
        for d in self._drops:
            p.setBrush(QColor(205, 238, 248, int(210 * clamp(d["life"], 0.0, 1.0))))
            p.drawEllipse(QPointF(d["x"], d["y"]), d["r"], d["r"])

    def _paint_bubbles(self, p: QPainter) -> None:
        sprite = assets.get("bubble")
        if sprite is not None:
            p.setPen(Qt.NoPen)
            for b in self._bubbles:
                d = b["r"] * 2.6
                p.drawPixmap(QRectF(b["x"] - d / 2.0, b["y"] - d / 2.0, d, d), sprite,
                             QRectF(sprite.rect()))
            return
        p.setPen(QPen(QColor(235, 250, 255, 130), 1.1))
        for b in self._bubbles:
            p.setBrush(QColor(235, 250, 255, 36))
            p.drawEllipse(QPointF(b["x"], b["y"]), b["r"], b["r"])
            # 高光点
            p.setBrush(QColor(255, 255, 255, 150))
            p.drawEllipse(QPointF(b["x"] - b["r"] * 0.32, b["y"] - b["r"] * 0.32),
                          b["r"] * 0.30, b["r"] * 0.30)

    def _paint_murk(self, p: QPainter, w: int, h: int) -> None:
        """浑浊度：整体色罩 + 底部沉积 + 漂浮颗粒 + 雾团。"""
        murk = 1.0 - self._clarity
        if murk <= 0.02:
            return
        base = _mix((150, 178, 126), (146, 122, 88), murk)
        wash = QColor(*base, int(36 + 96 * murk))
        p.fillRect(QRectF(0, SURFACE_Y, w, h - SURFACE_Y), wash)
        g = QLinearGradient(0, h * 0.5, 0, h)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(*base, int(70 * murk)))
        p.fillRect(QRectF(0, h * 0.5, w, h * 0.5), g)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(240, 236, 210, int(36 + 60 * murk)))
        for s in self._specks:
            x = s["x"] * w
            y = SURFACE_Y + s["y"] * (h - SURFACE_Y - GRAVEL_H)
            p.drawEllipse(QPointF(x, y), s["r"], s["r"])
        for blob in self._blobs:
            x = (blob["u"] * w + math.sin(self._t * 0.1 + blob["ph"]) * 40.0) % w
            y = SURFACE_Y + blob["v"] * (h - SURFACE_Y)
            rg = QRadialGradient(x, y, blob["r"])
            rg.setColorAt(0.0, QColor(*base, int(26 * murk)))
            rg.setColorAt(1.0, QColor(*base, 0))
            p.setBrush(rg)
            p.drawEllipse(QPointF(x, y), blob["r"], blob["r"])

    def _paint_surface(self, p: QPainter, w: int, _h: int) -> None:
        band = QLinearGradient(0, SURFACE_Y, 0, SURFACE_Y + 16)
        band.setColorAt(0.0, QColor(255, 255, 255, 55))
        band.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, SURFACE_Y, w, 16), band)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.6))
        path = QPainterPath()
        for x in range(0, w + 8, 8):
            y = SURFACE_Y + 1.0 + math.sin(x * 0.03 + self._t * 2.0) * 2.0
            if x == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
        path = QPainterPath()
        for x in range(0, w + 8, 8):
            y = SURFACE_Y + 5.0 + math.sin(x * 0.026 - self._t * 1.4) * 2.6
            if x == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.drawPath(path)

    def _paint_ripples(self, p: QPainter) -> None:
        for rp in self._ripples:
            a = max(0, int(110 - rp["r"] * 0.8))
            if a <= 0:
                continue
            p.setPen(QPen(QColor(255, 255, 255, a), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(rp["x"], rp["y"]), rp["r"], rp["r"] * 0.55)
            p.drawEllipse(QPointF(rp["x"], rp["y"]), rp["r"] * 0.55, rp["r"] * 0.3)

    def _paint_glass(self, p: QPainter, w: int, h: int) -> None:
        # 顶部金属亮边 / 底部沉积阴影
        top = QLinearGradient(0, 0, 0, 6)
        top.setColorAt(0.0, QColor(255, 255, 255, 60))
        top.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, 6), top)
        bot = QLinearGradient(0, h - 6, 0, h)
        bot.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.fillRect(QRectF(0, h - 6, w, 6), bot)
        # 四角暗角 → 玻璃纵深
        vg = QRadialGradient(w / 2.0, h / 2.0, max(w, h) * 0.72)
        vg.setColorAt(0.55, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 75))
        p.fillRect(QRectF(0, 0, w, h), vg)

        gl = QLinearGradient(0, 0, 34, 0)
        gl.setColorAt(0.0, QColor(255, 255, 255, 26))
        gl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, SURFACE_Y, 34, h - SURFACE_Y - 2), gl)
        gr = QLinearGradient(w, 0, w - 26, 0)
        gr.setColorAt(0.0, QColor(255, 255, 255, 20))
        gr.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(w - 26, SURFACE_Y, 26, h - SURFACE_Y - 2), gr)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), RADIUS, RADIUS)
        p.setPen(QPen(QColor(255, 255, 255, 54), 2))
        p.drawRoundedRect(QRectF(1.5, 1.5, w - 3.0, h - 3.0), RADIUS - 1, RADIUS - 1)

    # ---------------- 交互：拖动 / 缩放 / 点击涟漪 ----------------
    def _edge_at(self, pos) -> Qt.Edges | None:
        m = 8
        win = self.window()
        if win.isMaximized():
            return None
        edges = Qt.Edges()
        if pos.x() <= m:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - m:
            edges |= Qt.RightEdge
        if pos.y() <= m:
            edges |= Qt.TopEdge
        if pos.y() >= self.height() - m:
            edges |= Qt.BottomEdge
        return edges if edges else None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        btn = event.button()
        pos = event.position().toPoint()
        if btn == Qt.RightButton and self._mode:
            self.set_mode("")          # 右键退出工具模式
            event.accept()
            return
        if btn != Qt.LeftButton:
            return super().mousePressEvent(event)
        win = self.window()
        edges = self._edge_at(pos)
        if edges and not win.isMaximized():
            # 手动缩放：记录按下时的全局位置与窗口几何
            self._resize_edges = edges
            self._press_global = event.globalPosition().toPoint()
            self._press_geom = win.geometry()
            self.grabMouse()
            event.accept()
            return
        if self._mode == "feed":
            if pos.y() > SURFACE_Y + 4:
                self._drop_food(float(pos.x()), float(pos.y()))
            event.accept()
            return
        if self._mode == "net":
            self._scoop_at(float(pos.x()), float(pos.y()))
            self._net_dragging = True
            self.grabMouse()
            event.accept()
            return
        # 手动拖动：记录全局坐标偏移（不依赖 startSystemMove，兼容性最好）
        self._drag_active = True
        self._drag_offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
        self.grabMouse()
        if pos.y() > SURFACE_Y + 6:
            self._ripples.append({"x": float(pos.x()), "y": float(pos.y()), "r": 6.0})
            for f in self._fish:
                dx, dy = f.x - pos.x(), f.y - pos.y()
                d = math.hypot(dx, dy)
                if 0.1 < d < 130.0:
                    f.vx += dx / d * 160.0
                    f.vy += dy / d * 160.0
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._net_dragging:
            pos = event.position()
            self._scoop_at(float(pos.x()), float(pos.y()))
            event.accept()
            return
        if self._resize_edges:
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_active:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        edges = self._edge_at(event.position().toPoint())
        if edges:
            if edges in (Qt.LeftEdge, Qt.RightEdge):
                self.setCursor(Qt.SizeHorCursor)
            elif edges in (Qt.TopEdge, Qt.BottomEdge):
                self.setCursor(Qt.SizeVerCursor)
            elif edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
                self.setCursor(Qt.SizeFDiagCursor)
            else:
                self.setCursor(Qt.SizeBDiagCursor)
        elif not self._mode:
            self.unsetCursor()
        # 工具模式下保持自定义光标（鱼食/渔网）
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._net_dragging:
            self._net_dragging = False
            if self.mouseGrabber() is self:
                self.releaseMouse()
            event.accept()
            return
        if self._drag_active or self._resize_edges:
            self._drag_active = False
            self._resize_edges = Qt.Edges()
            if self.mouseGrabber() is self:
                self.releaseMouse()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _apply_resize(self, gp) -> None:
        """根据全局鼠标位置应用边缘缩放（含最小尺寸约束）。"""
        win = self.window()
        g = QRect(self._press_geom)
        dx = gp.x() - self._press_global.x()
        dy = gp.y() - self._press_global.y()
        e = self._resize_edges
        if e & Qt.LeftEdge:
            g.setLeft(min(g.left() + dx, g.right() - win.minimumWidth() + 1))
        if e & Qt.RightEdge:
            g.setRight(max(g.right() + dx, g.left() + win.minimumWidth() - 1))
        if e & Qt.TopEdge:
            g.setTop(min(g.top() + dy, g.bottom() - win.minimumHeight() + 1))
        if e & Qt.BottomEdge:
            g.setBottom(max(g.bottom() + dy, g.top() + win.minimumHeight() - 1))
        win.setGeometry(g)

    def mouseDoubleClickEvent(self, _event) -> None:  # noqa: N802
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
