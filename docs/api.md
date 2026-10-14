# REST 接口参考

本页说明后台服务（`app.py`）暴露的 HTTP 接口。基址默认 `http://127.0.0.1:10000`。

## 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/` | 返回网页看板（`static/index.html`） |
| GET  | `/api/state` | 返回鱼缸当前完整状态 + 历史趋势 |
| POST | `/api/control` | 施加一个外部条件，返回最新状态 |
| GET  | `/api/health` | 健康检查 |
| GET  | `/static/*` | 前端静态资源 |

---

## GET /api/state

返回当前鱼缸状态的完整快照，包含所有水质、种群、外部条件、健康度与历史。

**响应示例**

```json
{
  "time": 2.4,
  "fish": 6,
  "plants": 4,
  "bacteria": 12.0,
  "oxygen": 8.9,
  "ammonia": 0.0,
  "nitrite": 0.0,
  "nitrate": 19.8,
  "ph": 7.0,
  "temp": 26.0,
  "light": true,
  "food": 0.0,
  "waste": 0.29,
  "running": true,
  "speed": 1.0,
  "health": 100,
  "ideal": {
    "oxygen": [6.0, 9.0],
    "ammonia": [0.0, 0.25],
    "nitrite": [0.0, 0.25],
    "nitrate": [0.0, 40.0],
    "ph": [6.5, 7.5],
    "temp": [24.0, 28.0]
  },
  "history": [
    { "time": 0.2, "oxygen": 8.1, "ammonia": 0.016, "nitrite": 0.076, "nitrate": 20.0, "fish": 6, "health": 100 }
  ]
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `time` | number | 模拟经过小时数 |
| `fish` / `plants` | int | 鱼 / 水草数量 |
| `fish_age` | object | 鱼的年龄结构：`{ young, adult, senior, avg_age }`（幼鱼/成年/老年数 + 平均年龄 h） |
| `bacteria` | number | 硝化细菌群落量 |
| `oxygen` | number | 溶解氧 mg/L |
| `ammonia` | number | 氨氮 mg/L |
| `nitrite` | number | 亚硝酸盐 mg/L |
| `nitrate` | number | 硝酸盐 mg/L |
| `ph` | number | 酸碱度 |
| `temp` | number | 温度 °C |
| `light` | bool | 光照是否开启 |
| `food` | number | 缸内剩余食物量 |
| `waste` | number | 有机废物（生物负荷）累积 |
| `water_volume` | number | 当前水量 (L)，类比鱼缸大小 |
| `capacity` | int | 当前水量可承载的最大鱼数 |
| `running` | bool | 模拟是否运行 |
| `speed` | number | 时间倍速 |
| `health` | int | 生态健康度 0~100 |
| `ideal` | object | 各项水质指标的理想范围 `[lo, hi]` |
| `history` | array | 历史趋势点（最近 120 点） |

---

## POST /api/control

施加一个外部条件。请求体为 JSON：

```json
{ "action": "feed", "value": 3 }
```

**请求体（`ControlBody`）**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `action` | string | 是 | 动作名称，见下表 |
| `value` | number / string / bool / null | 否 | 动作的可选数值（部分动作用字符串，如温度模式） |

**支持的 `action`**

| action | value | 说明 |
| --- | --- | --- |
| `pause` / `resume` | — | 暂停 / 继续模拟 |
| `speed` | number | 速度倍速（0.1~10） |
| `feed` | number | 喂食量（可一次多份；前端步进器支持 1~99） |
| `light` | bool | 开/关灯 |
| `filter` | bool | 开关过滤设备（开启后过滤废物并小幅净化氨氮/硝酸盐） |
| `temp` | number | 直接设温度（同时更新恒温目标 `temp_set`；4~35°C） |
| `temp-mode` | string | 设置温度模式：`"constant"` 恒温 \| `"daynight"` 昼夜循环 |
| `temp-set` | number | 恒温模式的目标温度（4~35°C） |
| `temp-min` | number | 昼夜模式最低温（4~35°C） |
| `temp-max` | number | 昼夜模式最高温（4~35°C） |
| `day-hours` | number | 昼夜模式昼长（小时，0.1~48） |
| `night-hours` | number | 昼夜模式夜长（小时，0.1~48） |
| `add-plants` | number | 加草数量（可一次多份；步进器 1~99） |
| `add-bacteria` | number | 补菌量（可一次多份；步进器 1~99） |
| `add-fish` | number | 加鱼数量（可一次多份；步进器 1~99；新增的是**成年鱼**） |
| `add-water` | number | 加水量 (L，默认 +10)：扩容+稀释污染，可养更多鱼 |
| `reset` | — | 重置到初始状态 |

**响应**：与 `/api/state` 相同的完整状态快照（方便前端立即用返回值刷新）。

**示例**

```bash
curl -X POST http://127.0.0.1:10000/api/control \
  -H "Content-Type: application/json" \
  -d '{"action":"feed","value":3}'
```

---

## GET /api/health

健康检查，返回简化的运行状态。

```json
{ "status": "ok", "running": true, "health": 100 }
```

---

## 错误处理

- 非法请求体：FastAPI/Pydantic 返回 422 校验错误。
- 未知 `action`：`apply_control` 会忽略无法识别的动作，不报错，返回当前状态。
- 服务未就绪：前端轮询捕获错误并静默跳过，服务恢复后自动刷新。
