"""离屏渲染冒烟测试：不启动后台，注入假状态并保存预览 PNG。

用法（在 aquarium 目录下）：
    python -m desktop.smoke_test

生成 desktop/preview_clear.png（清澈、开灯、过滤开）
     desktop/preview_murky.png（浑浊、关灯、过滤关）
用于快速检查绘制效果与两种水质下的视觉区分。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from .app import MainWindow  # noqa: E402
from .metrics import clarity_of  # noqa: E402


def fake_state(**over) -> dict:
    s: dict = {
        "time": 52.5,
        "fish": 12,
        "fish_age": {"young": 4, "adult": 6, "senior": 2, "avg_age": 31.0},
        "plants": 9,
        "bacteria": 18.0,
        "oxygen": 7.8,
        "ammonia": 0.04,
        "nitrite": 0.06,
        "nitrate": 18.0,
        "ph": 7.02,
        "temp": 26.0,
        "light": True,
        "food": 0.8,
        "waste": 0.6,
        "filter_on": True,
        "water_volume": 120.0,
        "capacity": 18,
        "running": True,
        "speed": 1.0,
        "health": 94,
        "ideal": {},
        "history": [],
        "temp_mode": "constant",
        "temp_set": 26.0,
        "temp_min": 24.0,
        "temp_max": 28.0,
        "day_hours": 12.0,
        "night_hours": 12.0,
    }
    s.update(over)
    return s


def main() -> int:
    here = Path(__file__).resolve().parent
    app = QApplication(sys.argv)
    from .app import STYLE

    app.setStyleSheet(STYLE)
    win = MainWindow(connect=False)
    win.resize(1120, 680)
    win.show()

    cases = {
        "preview_clear.png": fake_state(),
        "preview_murky.png": fake_state(
            ammonia=1.1, nitrite=0.8, nitrate=90.0, waste=9.0,
            health=30, light=False, filter_on=False, food=3.5,
            plants=6, fish=8, oxygen=3.2,
        ),
    }
    for name, state in cases.items():
        win._on_state(state)
        for _ in range(90):  # 让本地动画跑约 3 秒
            win.tank._tick()
        win.repaint()
        out = here / name
        win.grab().save(str(out))
        print(f"saved {out}  clarity={clarity_of(state):.3f}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
