# 生态模拟模型

本页完整说明模拟引擎 `TankState` 的**状态变量、氮循环逻辑、每个步进内的公式、
参数、生态健康度计算**。模型定义见 `aquarium/app.py`。

> 约定：单步推进时长记为 `h`（小时）。`clamp(v, lo, hi)` 表示把 `v` 限制到 `[lo, hi]`。
> `rng()` 返回一个 0~1 的随机数（线程安全 LCG）。

## 1. 状态变量

### 种群

| 变量 | 说明 | 初始值 | 理想/约束 |
| --- | --- | --- | --- |
| `fish` | 鱼的总数（年龄分层群体的数量） | 6 | 0~40（承载力上限），受衰老/污染致死 |
| `fish_pop` | 鱼的年龄结构：每条鱼一个年龄值（小时）列表 | 见「鱼的年龄结构」 | — |
| `plants` | 水草数量 | 4 | 0~30（生长上限） |
| `bacteria` | 硝化细菌群落量 | 12 | 1~100（随底物增减） |

### 鱼的年龄结构

鱼采用**年龄分层**表示：`fish_pop` 是每条鱼的年龄（模拟小时）列表，`fish` 为总数。

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `mature_age` | 24h | 成熟年龄（约 0.8 年），之后进入成年期可繁殖 |
| `senior_age` | 96h | 老年年龄（约 3.2 年），之后死亡率显著升高 |
| `max_age` | 160h | 寿命上限（约 5.3 年），超过必然死亡 |
| `base_death` | 0.003/h | 基础死亡率（幼鱼/成年） |
| `senior_death` | 0.030/h | 老年额外死亡率 |
| `max_fish` | 40 | 种群承载力上限，避免无限繁殖 |

**年龄阶段**：
- 幼鱼（`age < mature_age`）：不繁殖，承受基础死亡率。
- 成年鱼（`mature_age ≤ age < senior_age`）：可繁殖。
- 老年鱼（`age ≥ senior_age`）：基础死亡率 + 老年额外死亡率。

`add-fish` 新增的是**成年鱼**（年龄取 `mature_age + 6h`）。状态快照额外输出
`fish_age = { young, adult, senior, avg_age }` 供前端展示。

### 水质

| 变量 | 说明 | 初始值 | 理想范围 |
| --- | --- | --- | --- |
| `oxygen` | 溶解氧 (mg/L) | 8.0 | 6 ~ 9 |
| `ammonia` | 氨氮 (mg/L) | 0.05 | 0 ~ 0.25 |
| `nitrite` | 亚硝酸盐 (mg/L) | 0.1 | 0 ~ 0.25 |
| `nitrate` | 硝酸盐 (mg/L) | 20.0 | 0 ~ 40 |
| `ph` | 酸碱度 | 7.0 | 6.5 ~ 7.5 |
| `temp` | 温度 (°C) | 26.0 | 24 ~ 28 |

### 外部条件 / 运行

| 变量 | 说明 | 初始值 |
| --- | --- | --- |
| `light` | 光照是否开启 | True |
| `food` | 缸内剩余食物量 | 0.0 |
| `waste` | 鱼代谢累积的有机废物（生物负荷，持续累积，指示性指标；开启过滤后随时间清除） | 0.0 |
| `filter_on` | 过滤设备是否开启（开启后过滤废物并小幅净化氨氮/硝酸盐） | False |
| `running` | 模拟是否运行 | True |
| `speed` | 时间倍速 (0.1~10) | 1.0 |
| `elapsed` | 模拟经过小时数 | 0.0 |

### 水量 / 鱼缸大小（容量）

| 变量 | 说明 | 初始值 |
| --- | --- | --- |
| `water_volume` | 当前水量 (L)，类比鱼缸大小 | 100.0 |
| `water_step` | 每次加水增量 (L) | 10.0 |
| `fish_per_100L` | 每 100L 水可承载的鱼数（承载力基准） | 15.0 |

**派生值**：
- `capacity = int(fish_per_100L * water_volume / 100)`：当前水量可承载的最大鱼数，
  加水扩容后线性提升（例如 100L→15 条，200L→30 条）。
- `dilution = 100 / water_volume`：稀释系数，水量越大，单位污染源产生的浓度越低
  （基准 100L）。

**加水（`add-water`）效果**：
- 增加 `water_volume`（默认 +10L，上限 1000L）。
- 按比例稀释当前氨氮/亚硝酸盐/硝酸盐浓度：
  `新浓度 = 旧浓度 * (旧水量 / 新水量)`。
- 繁殖上限由 `capacity` 决定（替代原固定 `max_fish`），因此加水能养更多鱼。
- 污染源在每步乘以 `dilution`（见 step 2），使稳态污染浓度与水量成反比。

### 温度模式

| 变量 | 说明 | 初始值 |
| --- | --- | --- |
| `temp_mode` | `"constant"` 恒温 \| `"daynight"` 昼夜循环 | `"constant"` |
| `temp` | 当前实际温度 °C | 26.0 |
| `temp_set` | 恒温模式的目标温度 °C | 26.0 |
| `temp_min` | 昼夜模式最低温 °C | 24.0 |
| `temp_max` | 昼夜模式最高温 °C | 28.0 |
| `day_hours` | 昼长（小时） | 12.0 |
| `night_hours` | 夜长（小时） | 12.0 |

## 2. 每步推进逻辑（step）

按顺序执行以下 13 个步骤，`h` 为步进小时数。

1. **鱼代谢产废物**（`waste` 为指示性存量，只增不减）
   ```
   waste += fish * 0.02 * h
   ```

2. **残饵腐烂 → 氨氮**
   ```
   food_decay = food * 0.25 * h
   food       = max(0, food - food_decay)
   ammonia    += fish * 0.012 * h + food_decay * 0.9
   ```

3. **环境对细菌活性的影响**
   ```
   temp_factor = clamp((temp - 16) / 12, 0.3, 1.4)
   o2_factor   = clamp(oxygen / 8, 0.4, 1.2)
   ```

4. **细菌：氨氮 → 亚硝酸盐**
   ```
   ammonia_removed = min(ammonia, bacteria * 0.02 * temp_factor * o2_factor * h)
   ammonia  -= ammonia_removed
   nitrite  += ammonia_removed * 0.9
   ```

5. **细菌：亚硝酸盐 → 硝酸盐**
   ```
   nitrite_removed = min(nitrite, bacteria * 0.03 * temp_factor * o2_factor * h)
   nitrite  -= nitrite_removed
   nitrate  += nitrite_removed * 0.8
   ```

6. **水草吸收**
   ```
   nitrate = max(0, nitrate - plants * 0.048 * h)
   ammonia = max(0, ammonia - plants * 0.01 * h)
   ```

7. **溶氧：光合作用（需光照）+ 鱼耗氧 + 表面补充 - 温度溶解损失**
   ```
   photosynthesis = plants * 0.15 * h   (若 light 否则 0)
   fish_o2        = fish * 0.04 * h
   oxygen = clamp(oxygen + photosynthesis - fish_o2 + 0.05*h - (temp-24)*0.01*h, 0, 14)
   ```

8. **细菌群落随底物增减**
   ```
   substrate = ammonia + nitrite
   growth    = 0.6 * h   (若 substrate > 0.02)   否则 -0.3 * h
   bacteria  = clamp(bacteria + growth, 1, 100)
   ```

9. **鱼：年龄推进、死亡与繁殖**（`_advance_fish`）
   对 `fish_pop` 中每条鱼（年龄 `age`）：
   ```
   new_age = age + h
   若 new_age >= max_age:         死亡（必然）；ammonia += 0.2（死鱼腐烂）
   否则:
     death_rate = base_death
     若 new_age >= senior_age: death_rate += senior_death
     death_rate += stress          # stress 来自氨氮/缺氧/亚硝酸盐
     若 rng() < death_rate * h:   死亡；ammonia += 0.2
     否则: 保留并更新年龄 new_age
   ```
   随后繁殖（略微过量繁殖：成年鱼在可容忍环境下持续产幼鱼）：
   ```
   env_factor = 1.0
     若 ammonia>0.5: env_factor *= 0.3      # 严重污染才抑制繁殖
     若 oxygen<4:    env_factor *= 0.3
     若 nitrite>0.5: env_factor *= 0.5
   feed_bonus = 1.0 + min(food, 2.0) * 0.5   # 有食物则繁殖更强（非硬门槛）
   adults = 满足 mature_age<=age<senior_age 的鱼数
   若 adults > 0:
     capacity_factor = 1.0 (若 len<capacity) 否则 0.5   # 容量为软上限
     repro_rate = 0.25 * env_factor * feed_bonus * capacity_factor
     for each adult: 若 rng() < repro_rate*h: fish_pop.append(0.0)  # 产一条幼鱼
   ```
   （`stress = (ammonia>0.5?0.1:0)+(oxygen<4?0.1:0)+(nitrite>0.5?0.05:0)`；
     繁殖不再以“剩余食物”为硬门槛，避免食物衰减导致永不繁殖；
     繁殖率高于死亡率，使种群**略微过量繁殖**。）

10. **pH 向中性漂移 + 噪声**
    ```
    ph = clamp(ph + (7.0-ph)*0.05*h + (rng()-0.5)*0.02, 4, 9)
    ```

11. **水草生长（需光照 + 硝酸盐充足）**
    ```
    若 light 且 nitrate>5 且 plants<30 且 rng()<0.04*h: plants+=1
    ```

11.5. **过滤设备**（`filter_on` 开启时）
    ```
    waste   = max(0, waste - 1.5 * h)      # 快速清除有机废物蓄积
    ammonia = max(0, ammonia - 0.05 * h)   # 辅助降低氨氮
    nitrate = max(0, nitrate - 0.3 * h)    # 辅助降低硝酸盐
    ```

12. **时间推进**
    ```
    elapsed += h
    ```

13. **更新温度**（`_update_temp`，按温度模式）
    ```
    若 temp_mode == "daynight":
        cycle  = day_hours + night_hours
        phase  = elapsed % cycle
        若 phase <= day_hours:                    # 白天 0 -> 1，昼长中点达峰值
            f = 0.5 - 0.5*cos(pi * phase / day_hours)
        否则:                                     # 夜晚 1 -> 0，夜长中点达谷值
            f = 0.5 + 0.5*cos(pi * (phase - day_hours) / night_hours)
        temp = temp_min + f * (temp_max - temp_min)
    否则 (恒温 constant):
        diff = temp_set - temp
        temp += diff * min(1.0, 0.3 * h)          # 向目标温度缓慢收敛
    temp = clamp(temp, 4, 35)
    ```

    昼夜波形说明：
    - 一个周期长度 = `day_hours + night_hours`（默认 24h）。
    - 白天温度从 `temp_min` 平滑升至 `temp_max`（在昼长中点达到峰值）。
    - 夜晚温度从 `temp_max` 平滑降至 `temp_min`（在夜长中点达到谷值）。
    - 恒温模式下 `temp` 缓慢逼近 `temp_set`，而非一步到位。

## 3. 生态健康度

遍历 6 项水质指标（`oxygen/ammonia/nitrite/nitrate/ph/temp`），
对每项计算偏离其理想范围的相对惩罚，累加后映射到 0~100。

```
penalty = Σ (对每项指标)
           若 v < ideal.lo: (ideal.lo - v) / ideal.lo
           若 v > ideal.hi: (v - ideal.hi) / ideal.hi
penalty = clamp(penalty, 0, 2)
health  = round( clamp(1 - penalty/2, 0, 1) * 100 )
```

- 前端按 `health` 着色：≥75 绿、45~74 黄、<45 红。

## 4. 历史记录

`record_history()` 每步记录一个快照点：

```
{ time, oxygen, ammonia, nitrite, nitrate, fish, health }
```

保留最近 **120** 个点（超出丢弃最早的）。前端用 `history` 绘制趋势折线图
（溶解氧、氨氮、硝酸盐三条序列）。

## 5. 外部条件控制（apply_control）

`apply_control(action, value)` 修改状态，见 [api.md](api.md) 的动作列表。
其中：

- `speed`：`speed = clamp(value, 0.1, 10)`，通过放大每步 `dt` 实现加速。
- `temp`：`temp = clamp(value, 4, 35)`。
- `reset`：调用 `TankState.__init__()` 恢复初始状态。
