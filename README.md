# LangCode

基于LangGraph构建的code agent项目

这个仓库随着笔者的学习进度逐渐完善，目标是：融入agent的多种先进技术包括但不限于：
1. context和memory管理
2. multi-agent编排
3. reflection与自我修正
4. MCP

```
LangCode/
├── src/
│   ├── main.py                   # 程序入口
│   │
│   ├── agents/                   # agent 实现
│   │   └── supervisor/           # supervisor agent
│   │       ├── graph.py          # graph 构建、编译、入口
│   │       ├── nodes.py          # 节点函数
│   │       ├── router.py         # 条件边 / 路由函数
│   │       └── tools.py          # 工具函数
│   │
│   └── shared/                   # 共享模块
│       ├── config.py             # 可调参数
│       ├── llm.py                # LLM 初始化
│       ├── state.py              # State TypedDict 定义
│       └── tools.py              # 共享工具函数

```

各文件的职责说明

### `src/main.py`
程序入口，负责初始化环境、组装 agent 并启动运行。

### `src/shared/` — 共享模块
| 文件 | 职责 |
|------|------|
| `state.py` | State TypedDict / Pydantic 定义，以及 reducer。所有 nodes、routers 都依赖它 |
| `llm.py` | LLM 实例化（模型、temperature 等），`bind_tools` 在这里做 |
| `config.py` | 可调参数，`RunnableConfig` 的 configurable schema（运行时可覆盖的参数） |
| `tools.py` | 共享工具函数，供多个 agent 复用 |

### `src/agents/supervisor/` — Supervisor Agent
| 文件 | 职责 |
|------|------|
| `graph.py` | `StateGraph` 构建、`add_node` / `add_edge` / `compile`，agent 的入口 |
| `nodes.py` | 各个节点函数，接受 state 返回 state 更新（如 LLM 调用节点） |
| `router.py` | 条件边函数，决定 graph 走哪条路 |
| `tools.py` | 该 agent 专用的工具函数 |

几个关键设计原则
1. `state.py` 是核心，其他模块都依赖它
   所有 nodes、routers 都 import State，所以避免 `state.py` 反向 import 其他模块，防止循环依赖。
2. `llm.py` 独立出来有意义
   LLM 实例可在多处复用，集中管理模型配置（API key、base_url、temperature）。
3. `shared/` 与 `agents/` 分离
   共享模块不依赖任何 agent 实现，agent 可以按需新增目录（如 `agents/researcher/`）。