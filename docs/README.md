# 鱼缸水生态系统模拟 · 文档导航

本目录是项目的**技术文档**，说明系统架构、模拟模型、接口和网页看板。
文档会**随实现持续推进**——每新增/调整功能，对应章节同步更新。

## 文档清单

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 系统架构、组件、运行流程、技术栈 |
| [model.md](model.md) | 生态模拟模型：状态变量、氮循环逻辑、公式、参数、健康度 |
| [api.md](api.md) | REST 接口参考（参数、数据、示例） |
| [dashboard.md](dashboard.md) | 网页看板的功能、面板、控件与交互 |
| [roadmap.md](roadmap.md) | 扩展方向 + 变更历史（Changelog） |

## 快速开始

```bash
cd aquarium
python -m pip install -r requirements.txt
python app.py                # 或 uvicorn app:app --port 10000
# 浏览器打开 http://127.0.0.1:10000
```

> 默认端口为 `10000`，可通过环境变量 `AQUARIUM_PORT` 覆盖（见 [architecture.md](architecture.md)）。
> 注意：不使用 8000。

## 当前状态（最近一次更新）

- **平台**：Python 3.12 + FastAPI + Uvicorn；前端为原生 HTML/CSS/JS（无框架）
- **运行模式**：后台模拟线程 + HTTP 轮询看板
- **已实现**：氮循环水质模拟、5 类种群动态、生态健康度、9 种外部条件控制、
  实时看板（指标/种群/健康度/趋势折线）、REST 接口
- **未实现 / 候选扩展**：见 [roadmap.md](roadmap.md)
