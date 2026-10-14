"""
鱼缸水生态系统模拟 —— 后台服务
=================================

一个用 FastAPI 搭建的鱼缸水生态系统模拟后台服务：
- 在后台按时间步进模拟淡水鱼缸的氮循环和水质变化
- 通过 REST API 对外提供当前状态，并接受外部条件控制
- 同时托管一个网页看板（static/index.html）

运行：
    python -m pip install -r requirements.txt   # 首次
    uvicorn app:app --host 127.0.0.1 --port 10000
    # 或
    python app.py

然后浏览器打开  http://127.0.0.1:10000

端口说明：
    - 默认端口为 10000（位于 10000 之后），不占用 8000。
    - 可用环境变量 AQUARIUM_PORT 覆盖，例如：
          set AQUARIUM_PORT=10001   (Windows)
          export AQUARIUM_PORT=10001   (Linux/macOS)
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# 生态系统模拟模型
# --------------------------------------------------------------------------- #
# 模拟一个淡水鱼缸：
#   - 鱼 (fish) 产生废物 -> 氨氮 (ammonia)
#   - 硝化细菌 (bacteria) 把氨氮转化为亚硝酸盐 (nitrite)，再转化为硝酸盐 (nitrate)
#   - 水草 (plants) 在光照下消耗硝酸盐并产生溶解氧 (oxygen)
#   - 温度、光照、鱼数、细菌群落、食物共同影响整个氮循环的平衡
#   - 鱼会因氨氮过高 / 缺氧 / 亚硝酸盐过高而死亡，条件良好时繁殖


class TankState:
    """鱼缸的一个时间快照（数值 + 历史）。"""

    def __init__(self) -> None:
        # 基础种群
        # 鱼采用年龄分层表示：self.fish_pop 是每条鱼的年龄（小时）列表。
        # fish 为总数（兼容旧快照/前端）。
        self.mature_age = 24.0     # 成熟年龄（约 0.8 年，之后可繁殖）
        self.senior_age = 96.0     # 老年年龄（约 3.2 年，之后死亡率升高）
        self.max_age = 160.0       # 寿命上限（约 5.3 年，超过自然死亡）
        self.base_death = 0.003    # 基础死亡率 / 小时
        self.senior_death = 0.030  # 老年额外死亡率 / 小时
        self.max_fish = 40         # 种群承载力上限（避免无限繁殖）
        # 初始 6 条鱼：3 成年 + 2 幼鱼 + 1 老年（便于看到年龄结构演化）
        self.fish_pop: list[float] = [60.0, 70.0, 80.0, 10.0, 15.0, 110.0]
        self.plants = 4
        self.bacteria = 12.0

        # 水质指标
        self.oxygen = 8.0        # 溶解氧 mg/L（理想 6~9）
        self.ammonia = 0.05      # 氨氮 mg/L（理想 0~0.25）
        self.nitrite = 0.1       # 亚硝酸盐 mg/L（理想 0~0.25）
        self.nitrate = 20.0      # 硝酸盐 mg/L（理想 0~40）
        self.ph = 7.0            # 酸碱度（理想 6.5~7.5）
        self.temp = 26.0         # 当前温度 °C（理想 24~28）

        # 温度模式
        self.temp_mode = "constant"   # "constant" 恒温 | "daynight" 昼夜循环
        self.temp_set = 26.0          # 恒温模式的目标温度
        self.temp_min = 24.0          # 昼夜模式最低温
        self.temp_max = 28.0          # 昼夜模式最高温
        self.day_hours = 12.0         # 昼长（小时）
        self.night_hours = 12.0       # 夜长（小时）

        # 外部条件
        self.light = True        # 光照是否开启
        self.food = 0.0          # 缸内剩余食物量（可喂食）
        self.waste = 0.0         # 鱼产生的有机废物累积
        self.filter_on = False   # 过滤设备是否开启（开启后随时间过滤废物）

        # 水量 / 鱼缸大小（类比容量，加水可扩容并稀释污染）
        self.water_volume = 100.0  # 当前水量 L（初始 100L）
        self.water_step = 10.0     # 每次加水增量 L
        self.fish_per_100L = 15.0  # 每 100L 水可承载的鱼数（承载力基准）

        # 运行控制
        self.running = True
        self.speed = 1.0         # 时间倍速
        self.elapsed = 0.0       # 模拟经过的小时数

        # 历史（用于前端趋势图）
        self.history: list[dict[str, float]] = []

    # ---------------- 理想范围 ----------------
    @property
    def ideal(self) -> dict[str, tuple[float, float]]:
        return {
            "oxygen": (6.0, 9.0),
            "ammonia": (0.0, 0.25),
            "nitrite": (0.0, 0.25),
            "nitrate": (0.0, 40.0),
            "ph": (6.5, 7.5),
            "temp": (24.0, 28.0),
        }

    # ---------------- 工具函数 ----------------
    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    # ---------------- 鱼的年龄结构 ----------------
    @property
    def fish(self) -> int:
        """当前鱼总数（兼容旧快照/前端）。"""
        return len(self.fish_pop)

    def add_fish(self, count: int = 1) -> None:
        """新增成年鱼（个体年龄取成熟年龄附近）。"""
        for _ in range(int(count)):
            self.fish_pop.append(self.mature_age + 6.0)

    def age_breakdown(self) -> dict[str, Any]:
        """统计年龄结构：幼鱼 / 成年 / 老年 数量与平均年龄。"""
        young = sum(1 for a in self.fish_pop if a < self.mature_age)
        senior = sum(1 for a in self.fish_pop if a >= self.senior_age)
        adult = len(self.fish_pop) - young - senior
        avg = sum(self.fish_pop) / len(self.fish_pop) if self.fish_pop else 0.0
        return {
            "young": young,
            "adult": adult,
            "senior": senior,
            "avg_age": round(avg, 1),
        }

    @property
    def capacity(self) -> int:
        """当前水量可承载的最大鱼数（随水量扩容而提高）。"""
        return int(self.fish_per_100L * self.water_volume / 100.0)

    @property
    def dilution(self) -> float:
        """稀释系数：水量越大，单位污染源产生的浓度越低（基准 100L）。"""
        return 100.0 / self.water_volume

    def add_water(self, amount: float = 10.0) -> None:
        """加水扩容：增加水量，并按比例稀释当前污染浓度（氨氮/亚硝酸盐/硝酸盐）。"""
        old = self.water_volume
        self.water_volume = min(old + float(amount), 1000.0)
        factor = old / self.water_volume  # 新浓度 = 旧浓度 * 旧水量/新水量
        self.ammonia *= factor
        self.nitrite *= factor
        self.nitrate *= factor

    def _advance_fish(self, h: float, rng) -> None:
        """鱼类年龄推进、死亡与繁殖。"""
        # 环境压力致死率（污染 / 缺氧 / 亚硝酸盐）
        stress = 0.0
        if self.ammonia > 0.5:
            stress += 0.10
        if self.oxygen < 4.0:
            stress += 0.10
        if self.nitrite > 0.5:
            stress += 0.05

        survivors = []
        for age in self.fish_pop:
            new_age = age + h
            # 超过寿命上限必然死亡
            if new_age >= self.max_age:
                self.ammonia += 0.2  # 死鱼腐烂
                continue
            # 年龄相关死亡率
            death_rate = self.base_death
            if new_age >= self.senior_age:
                death_rate += self.senior_death
            death_rate += stress
            if rng() < death_rate * h:
                self.ammonia += 0.2  # 死鱼腐烂
                continue
            survivors.append(new_age)
        self.fish_pop = survivors

        # 繁殖：成年鱼在可容忍环境下持续产幼鱼（略微过量繁殖）。
        # 不再以“剩余食物”为硬门槛（食物会衰减，导致无法繁殖）；
        # 环境越健康、食物越充足，繁殖越强；即使环境稍差也仍会繁殖。
        env_factor = 1.0
        if self.ammonia > 0.5:
            env_factor *= 0.3
        if self.oxygen < 4.0:
            env_factor *= 0.3
        if self.nitrite > 0.5:
            env_factor *= 0.5
        feed_bonus = 1.0 + min(self.food, 2.0) * 0.5   # 有食物则繁殖更强
        adults = sum(1 for a in self.fish_pop if self.mature_age <= a < self.senior_age)
        if adults > 0:
            # 容量作为“软上限”：超过后仍可繁殖但减半（自然以污染压力调节，不硬卡死）
            capacity_factor = 1.0 if len(self.fish_pop) < self.capacity else 0.5
            repro_rate = 0.25 * env_factor * feed_bonus * capacity_factor
            for _ in range(adults):
                if rng() < repro_rate * h:
                    self.fish_pop.append(0.0)

    # ---------------- 单步推进 ----------------
    def step(self, dt: float) -> None:
        """推进 dt 小时（带噪声的确定性模型，使用随机游走，但步长独立）。"""
        if not self.running:
            return
        h = dt

        rng = _rng()

        # 1) 鱼代谢产生废物
        self.waste += self.fish * 0.02 * h

        # 2) 剩余食物腐烂 -> 氨氮（浓度受水量稀释：水越多，同量污染浓度越低）
        food_decay = self.food * 0.25 * h
        self.food = max(0.0, self.food - food_decay)
        self.ammonia += (self.fish * 0.003 + food_decay * 0.2) * self.dilution * h

        # 3) 温度与氧对细菌活性的影响
        temp_factor = self._clamp((self.temp - 16.0) / 12.0, 0.3, 1.4)
        o2_factor = self._clamp(self.oxygen / 8.0, 0.4, 1.2)

        # 4) 细菌把氨氮 -> 亚硝酸盐
        ammonia_removed = min(
            self.ammonia,
            self.bacteria * 0.03 * temp_factor * o2_factor * h,
        )
        self.ammonia -= ammonia_removed
        self.nitrite += ammonia_removed * 0.9

        # 5) 细菌把亚硝酸盐 -> 硝酸盐
        nitrite_removed = min(
            self.nitrite,
            self.bacteria * 0.03 * temp_factor * o2_factor * h,
        )
        self.nitrite -= nitrite_removed
        self.nitrate += nitrite_removed * 0.8

        # 6) 水草吸收硝酸盐，并少量吸收氨氮
        self.nitrate = max(0.0, self.nitrate - self.plants * 0.048 * h)
        self.ammonia = max(0.0, self.ammonia - self.plants * 0.01 * h)

        # 7) 溶氧：光照下水草光合作用产氧；鱼耗氧；水面/过滤补充；温度越高溶解越少
        photosynthesis = self.plants * 0.15 * h if self.light else 0.0
        fish_o2 = self.fish * 0.04 * h
        self.oxygen += photosynthesis - fish_o2 + 0.05 * h - (self.temp - 24.0) * 0.01 * h
        self.oxygen = self._clamp(self.oxygen, 0.0, 14.0)

        # 8) 细菌群落随底物（氨氮+亚硝酸盐）增减
        substrate = self.ammonia + self.nitrite
        growth = 0.6 * h if substrate > 0.02 else -0.3 * h
        self.bacteria = self._clamp(self.bacteria + growth, 1.0, 100.0)

        # 9) 鱼：年龄推进、死亡与繁殖（年龄分层模型）
        self._advance_fish(h, rng)

        # 10) pH 缓慢向中性漂移 + 噪声
        self.ph += (7.0 - self.ph) * 0.05 * h + (rng() - 0.5) * 0.02
        self.ph = self._clamp(self.ph, 4.0, 9.0)

        # 11) 光照且硝酸盐充足时水草缓慢生长
        if self.light and self.nitrate > 5.0 and self.plants < 30 and rng() < 0.04 * h:
            self.plants += 1

        # 11.5) 过滤设备：开启时随时间过滤废物，并小幅净化氨氮/硝酸盐
        if self.filter_on:
            self.waste = max(0.0, self.waste - 1.5 * h)          # 快速清除有机废物蓄积
            self.ammonia = max(0.0, self.ammonia - 0.05 * h)     # 辅助降低氨氮
            self.nitrate = max(0.0, self.nitrate - 0.3 * h)      # 辅助降低硝酸盐

        # 12) 时间推进
        self.elapsed += h

        # 13) 更新温度（恒温收敛 或 昼夜循环波动）
        self._update_temp(h)

    # ---------------- 温度 ----------------
    def _update_temp(self, h: float) -> None:
        """根据温度模式更新当前温度 temp。

        - 恒温模式 constant：temp 向 temp_set 缓慢收敛（每步靠近一点）。
        - 昼夜模式 daynight：在 temp_min ~ temp_max 之间按昼夜周期平滑波动。
          白天（昼长内）温度升高至峰值，夜晚降低至谷值。
        """
        if self.temp_mode == "daynight":
            cycle = max(self.day_hours + self.night_hours, 0.1)
            phase = self.elapsed % cycle
            if phase <= self.day_hours and self.day_hours > 0:
                # 白天：0 -> 1（在昼长中点达到峰值 temp_max）
                f = 0.5 - 0.5 * math.cos(math.pi * phase / self.day_hours)
            else:
                # 夜晚：1 -> 0（在夜长中点达到谷值 temp_min）
                night_phase = phase - self.day_hours
                npd = max(self.night_hours, 0.01)
                f = 0.5 + 0.5 * math.cos(math.pi * night_phase / npd)
            self.temp = self.temp_min + f * (self.temp_max - self.temp_min)
        else:
            # 恒温模式：向目标温度收敛
            diff = self.temp_set - self.temp
            self.temp += diff * min(1.0, 0.3 * h)
        self.temp = self._clamp(self.temp, 4.0, 35.0)

    # ---------------- 健康度 ----------------
    def health(self) -> int:
        penalty = 0.0
        for key, (lo, hi) in self.ideal.items():
            v = getattr(self, key)
            if v < lo:
                penalty += (lo - v) / lo
            elif v > hi:
                penalty += (v - hi) / hi
        penalty = self._clamp(penalty, 0.0, 2.0)
        return round(self._clamp(1.0 - penalty / 2.0, 0.0, 1.0) * 100)

    # ---------------- 记录历史 ----------------
    def record_history(self) -> None:
        self.history.append({
            "time": round(self.elapsed, 1),
            "oxygen": round(self.oxygen, 1),
            "ammonia": round(self.ammonia, 3),
            "nitrite": round(self.nitrite, 3),
            "nitrate": round(self.nitrate, 1),
            "fish": self.fish,
            "health": self.health(),
        })
        if len(self.history) > 120:
            self.history.pop(0)

    # ---------------- 导出快照 ----------------
    def snapshot(self) -> dict[str, Any]:
        age = self.age_breakdown()
        return {
            "time": round(self.elapsed, 1),
            "fish": self.fish,
            "fish_age": age,
            "plants": self.plants,
            "bacteria": round(self.bacteria, 0),
            "oxygen": round(self.oxygen, 1),
            "ammonia": round(self.ammonia, 3),
            "nitrite": round(self.nitrite, 3),
            "nitrate": round(self.nitrate, 1),
            "ph": round(self.ph, 2),
            "temp": round(self.temp, 1),
            "light": self.light,
            "food": round(self.food, 2),
            "waste": round(self.waste, 2),
            "filter_on": self.filter_on,
            "water_volume": round(self.water_volume, 1),
            "capacity": self.capacity,
            "running": self.running,
            "speed": self.speed,
            "health": self.health(),
            "ideal": self.ideal,
            "history": list(self.history),
            # 温度模式
            "temp_mode": self.temp_mode,
            "temp_set": round(self.temp_set, 1),
            "temp_min": round(self.temp_min, 1),
            "temp_max": round(self.temp_max, 1),
            "day_hours": round(self.day_hours, 1),
            "night_hours": round(self.night_hours, 1),
        }

    # ---------------- 外部条件控制 ----------------
    def apply_control(self, action: str, value: Any = None) -> None:
        if action == "pause":
            self.running = False
        elif action == "resume":
            self.running = True
        elif action == "speed":
            self.speed = self._clamp(float(value or 1.0), 0.1, 10.0)
        elif action == "feed":
            self.food += float(value or 1.0)
        elif action == "light":
            self.light = bool(value)
        elif action == "filter":
            self.filter_on = bool(value)
        elif action == "temp":
            # 兼容：直接设温度；若处于恒温模式则同时更新目标温度
            t = self._clamp(float(value or 26.0), 4.0, 35.0)
            self.temp = t
            self.temp_set = t
        # ---- 温度模式相关 ----
        elif action == "temp-mode":
            mode = str(value)
            self.temp_mode = mode if mode in ("constant", "daynight") else "constant"
        elif action == "temp-set":
            self.temp_set = self._clamp(float(value or 26.0), 4.0, 35.0)
        elif action == "temp-min":
            self.temp_min = self._clamp(float(value or 24.0), 4.0, 35.0)
        elif action == "temp-max":
            self.temp_max = self._clamp(float(value or 28.0), 4.0, 35.0)
        elif action == "day-hours":
            self.day_hours = self._clamp(float(value or 12.0), 0.1, 48.0)
        elif action == "night-hours":
            self.night_hours = self._clamp(float(value or 12.0), 0.1, 48.0)
        elif action == "add-plants":
            self.plants += int(value or 1)
        elif action == "add-bacteria":
            self.bacteria = self._clamp(self.bacteria + float(value or 5.0), 1.0, 100.0)
        elif action == "add-fish":
            self.add_fish(int(value or 1))
        elif action == "add-water":
            self.add_water(float(value or self.water_step))
        elif action == "reset":
            self.__init__()


# --------------------------------------------------------------------------- #
# 随机性（线性同余，便于可复现；线程安全）
# --------------------------------------------------------------------------- #
_rng_lock = threading.Lock()
_rng_state = [12345]


def _rng() -> "function":
    """返回一个线程安全的 0~1 随机函数（LCG）。"""
    def _next() -> float:
        global _rng_state
        with _rng_lock:
            _rng_state[0] = (_rng_state[0] * 1103515245 + 12345) & 0x7FFFFFFF
            return _rng_state[0] / 0x7FFFFFFF
    return _next


# --------------------------------------------------------------------------- #
# 后台模拟线程
# --------------------------------------------------------------------------- #
tank = TankState()


def _sim_loop() -> None:
    """每 0.5 秒推进一次模拟，速度受 speed 控制。"""
    last_record = 0.0
    while True:
        if tank.running:
            tank.step(0.2 * tank.speed)
            # 大约每 0.5 秒记录一个历史点（受速度影响）
            tank.record_history()
        time.sleep(0.5)


# --------------------------------------------------------------------------- #
# FastAPI 应用
# --------------------------------------------------------------------------- #
app = FastAPI(title="鱼缸水生态系统模拟", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """禁用浏览器缓存，确保 F5 每次都能拿到最新前端（解决旧版 JS 缓存问题）。"""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# 托管前端静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


class ControlBody(BaseModel):
    action: str = Field(..., description="控制动作，如 feed/light/temp-mode/temp-set/pause/reset")
    value: Any = Field(default=None, description="动作的可选数值（number/string/bool）")


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """返回鱼缸当前完整状态 + 历史趋势。"""
    return tank.snapshot()


@app.post("/api/control")
def control(body: ControlBody) -> dict[str, Any]:
    """施加一个外部条件（喂食、光照、温度、种群、暂停等）。"""
    tank.apply_control(body.action, body.value)
    return tank.snapshot()


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {"status": "ok", "running": tank.running, "health": tank.health()}


if __name__ == "__main__":
    import os

    import uvicorn

    # 默认端口 10000（10000 之后），可用环境变量 AQUARIUM_PORT 覆盖
    port = int(os.environ.get("AQUARIUM_PORT", "10000"))

    # 启动后台模拟线程
    threading.Thread(target=_sim_loop, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
