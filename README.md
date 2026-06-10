# LangCode

基于 LangGraph 构建的 AI Code Agent，具备完整的生产级能力。

## 核心特性

- **Tool Use / Function Calling** — 7 个内置工具，涵盖文件读写、代码执行、Shell 命令、API 请求
- **Memory 记忆管理** — SQLite + FTS5 全文搜索，零外部依赖的持久化记忆系统
- **Planning 任务规划** — Plan-and-Execute 模式，LLM 自动分解复杂任务为可执行步骤
- **Multi-Agent 多 Agent 协作** — Supervisor 编排 Code/Research/Review 三个专业子 Agent

## 项目结构

```
LangCode/
├── src/LangCode/
│   ├── main.py                          # 程序入口，集成所有子系统
│   │
│   ├── shared/                          # 共享基础设施
│   │   ├── state.py                     # LCState 全局状态定义
│   │   ├── llm.py                       # LLM 初始化
│   │   ├── config.py                    # 可调参数
│   │   ├── tools.py                     # 7 个共享工具（read/write/edit/search/shell/python/api）
│   │   ├── command.py                   # 命令常量
│   │   └── logger.py                    # 日志系统
│   │
│   ├── memory/                          # 记忆管理系统
│   │   ├── store.py                     # SQLiteMemoryStore，FTS5 全文搜索
│   │   ├── manager.py                   # MemoryManager，自动提取/检索/注入
│   │   └── tools.py                     # memory_save / search / list 工具
│   │
│   ├── planning/                        # 任务规划系统
│   │   ├── schema.py                    # Plan / PlanStep 模型
│   │   ├── planner.py                   # LLM 生成执行计划
│   │   ├── executor.py                  # 逐步执行计划
│   │   ├── reflector.py                 # 评估结果，决定继续/重规划
│   │   └── tools.py                     # plan_create / plan_show 工具
│   │
│   └── agents/                          # 多 Agent 协作
│       ├── base.py                      # BaseAgent 抽象基类
│       ├── delegate_tools.py            # 委托工具，Supervisor 调度子 Agent
│       ├── supervisor/
│       │   ├── graph.py                 # ReAct + Plan-and-Execute 双模式编排器
│       │   └── prompts.py               # 系统提示词
│       ├── code_agent/graph.py          # 代码生成/编辑/调试
│       ├── research_agent/graph.py      # 文件搜索/阅读/分析
│       └── review_agent/graph.py        # 代码审查/安全分析
│
└── tests/                               # 测试（122 个）
    ├── conftest.py                      # 共享 fixtures
    ├── shared/                          # 工具和提示词测试
    ├── memory/                          # 记忆系统测试
    ├── planning/                        # 规划系统测试
    └── agents/                          # Agent 路由和委托测试
```

## 快速开始

```bash
# 安装依赖
uv sync

# 配置 LLM（默认使用 MiMo-v2.5-pro）
export LC_MODEL_NAME="your-model"
export LC_API_KEY="your-api-key"
export LC_BASE_URL="your-base-url"

# 运行 Agent
uv run python src/LangCode/main.py

# 运行测试
uv run pytest tests/ -v
```

## 架构设计

### 双模式编排

Supervisor Agent 支持两种工作模式，根据任务复杂度自动切换：

- **ReAct 模式** — 简单任务直接推理+行动，快速响应
- **Plan-and-Execute 模式** — 复杂任务先规划再执行，支持反思和重规划

### 记忆系统

基于 SQLite + FTS5，零外部依赖：

- 对话结束时自动提取值得记忆的信息
- FTS5 全文搜索 + LIKE 模糊匹配双通道检索
- 记忆注入系统提示词，提供上下文感知

### 多 Agent 协作

Supervisor 通过委托工具调度专业子 Agent：

- `delegate_to_code` — 代码生成、编辑、调试
- `delegate_to_research` — 文件搜索、阅读、分析
- `delegate_to_review` — 代码审查、安全分析、质量评估

### 安全沙箱

`run_python` 工具在隔离子进程中执行代码：

- 模块级 import 黑名单（os、subprocess、socket 等）
- 256MB 内存上限，watchdog 线程实时监控
- 可配置超时，防止无限循环

## 技术栈

- Python 3.11+
- LangGraph + LangChain
- Pydantic（工具 Schema 和数据校验）
- SQLite + FTS5（记忆存储）
