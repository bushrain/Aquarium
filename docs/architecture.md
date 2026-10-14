# 系统架构

本页说明鱼缸水生态系统模拟的**整体架构、组件划分、运行流程与技术栈**。

## 技术栈

- **后端**：Python 3.12 + [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn + Pydantic
- **前端**：原生 HTML5 + CSS3 + JavaScript（无框架、无打包器、无第三方图表库）
- **通信**：HTTP REST + 前端定时轮询（每 1 秒）

## 组件划分

```
aquarium/
├── app.py                  # FastAPI 应用 + 模拟引擎 + 后台线程 + REST 接口 + 静态托管
├── requirements.txt        # Python 依赖
├── README.md               # 用户说明
├── docs/                   # 技术文档（本目录）
│   ├── README.md           # 文档导航
│   ├── architecture.md     # 架构（本页）
│   ├── model.md            # 模拟模型
│   ├── api.md              # 接口参考
│   ├── dashboard.md        # 看板说明
│   └── roadmap.md          # 扩展方向 + 变更历史
└── static/                 # 网页看板前端
    ├── index.html          # 看板结构
    ├── app.js              # 轮询、渲染、控件逻辑
    └── style.css           # 样式
```

## 运行时架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        Python (FastAPI) 进程                      │
│                                                                    │
│   ┌───────────────┐        ┌────────────────────────────┐        │
│   │  模拟引擎      │        │  FastAPI 应用               │        │
│   │  TankState     │        │  /api/state                │        │
│   │  step()        │ 读取   │  /api/control              │        │
│   │  health()      │◄──────►│  /api/health               │        │
│   │  apply_control │        │  / (静态 index.html)        │        │
│   └───────┬────────┘        └───────────┬────────────────┘        │
│           │ 后台线程每 0.5s 驱动          │                         │
│           │  (threading + timer)         │ HTTP                    │
└───────────┼──────────────────────────────┼─────────────────────────┘
            │                              │
            ▼                              ▼
   模拟状态推进(内存)             ┌──────────────────────────┐
                                 │   浏览器网页看板           │
                                 │  static/index.html        │
                                 │  app.js: 每 1s 轮询 /api/state
                                 │  控件 → POST /api/control │
                                 └──────────────────────────┘
```

## 关键设计点

1. **模拟与 Web 解耦**：模拟引擎是纯 Python 类（`TankState`），不依赖 Web 框架；
   FastAPI 只是读/写它的状态。便于将引擎替换成 C++/独立进程等服务化。
2. **单例状态**：模块级 `tank = TankState()` 作为当前鱼缸的唯一实例，所有请求共享。
3. **后台线程驱动**：独立 `_sim_loop()` 线程以固定 0.5s 周期推进模拟，
   `speed` 倍速通过放大每次步进的 `dt` 实现（而非改变线程频率）。
4. **线程安全**：随机数源用 `threading.Lock` 保护的 LCG，避免并发竞争。
5. **确定性伪随机**：使用线性同余生成器（LCG），初始化固定种子，便于复现实验。
6. **前端无依赖**：趋势图用 Canvas 手绘，指标量表用 CSS，无需引入图表库或框架。
7. **默认端口 10000**：`uvicorn.run` 默认监听 127.0.0.1:10000（不使用 8000，
   处于 10000 之后）；可通过环境变量 **`AQUARIUM_PORT`** 覆盖，例如
   `set AQUARIUM_PORT=10001`（Windows）或 `export AQUARIUM_PORT=10001`（Linux/macOS）。

## 运行流程

1. 启动 `app.py`：创建 `TankState`，启动 `_sim_loop()` 后台线程，`uvicorn` 监听默认端口 **10000**。
2. 浏览器打开 `http://127.0.0.1:10000`，服务返回 `static/index.html`。
3. 前端 `app.js` 启动时立即 `GET /api/state` 渲染初始看板，并 `setInterval` 每 1s 刷新。
4. 后台线程每 0.5s 调用 `tank.step(...)`，并把快照写入 `tank.history`（保留最近 120 点）。
5. 前端每次轮询拿到最新状态与历史，重绘指标、种群、健康度与趋势图。
6. 用户点击控件 → `POST /api/control` → `tank.apply_control(...)` 修改状态 →
   返回最新快照，前端立即用返回值刷新，无需等下一次轮询。
