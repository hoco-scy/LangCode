# LangCode

基于 LangGraph 构建的 AI Code Agent，具备完整的生产级能力。

## 核心特性

- **多工具集成** — 25+ 内置工具：文件读写、Shell/Python 执行、Git 操作（status/diff/log/blame）、API 请求
- **AST 结构化编辑** — 基于 tree-sitter 的代码级操作：重命名、添加参数/方法/import，语义级精确修改
- **Memory 记忆管理** — SQLite + FTS5 全文搜索，零外部依赖的持久化记忆系统，自动提取与检索
- **Planning 任务规划** — Plan-and-Execute 模式，LLM 自动分解复杂任务为可执行步骤，支持反思与重规划
- **Multi-Agent 多 Agent 协作** — Supervisor 编排 Code/Research/Review 三个专业子 Agent，各具专业化流程图
- **MCP 集成** — 支持 Model Context Protocol，动态发现和注册外部工具
- **上下文窗口管理** — tiktoken 精确计数 + 启发式回退，滑动窗口裁剪 + LLM 摘要压缩
- **代码沙箱** — `run_python` 在隔离子进程中执行，模块级 import 黑名单 + 256MB 内存上限 + watchdog 监控

## 项目结构

```
LangCode/
├── src/LangCode/
│   ├── main.py                          # 程序入口，集成所有子系统
│   │
│   ├── shared/                          # 共享基础设施
│   │   ├── state.py                     # LCState 全局状态定义
│   │   ├── llm.py / config.py           # LLM 初始化与配置
│   │   ├── tools.py                     # 11 个基础工具（文件/Git/Shell/Python/API）
│   │   ├── schemas.py                   # Pydantic 结构化响应模型（13 个类型）
│   │   ├── ast_editor.py                # tree-sitter AST 编辑器核心
│   │   ├── ast_tools.py                 # 6 个 AST 操作工具的 LangChain 包装
│   │   ├── mcp_client.py                # MCP 协议客户端（支持 stdio 传输）
│   │   ├── context.py                   # 上下文窗口管理（token 计数/裁剪/摘要）
│   │   ├── routing.py                   # 共享路由（工具调用判断）
│   │   ├── prompts.py                   # 平台级 system prompt
│   │   ├── command.py                   # 命令常量
│   │   └── logger.py                    # 日志系统
│   │
│   ├── memory/                          # 记忆管理系统
│   │   ├── store.py                     # SQLiteMemoryStore，FTS5 全文搜索
│   │   ├── manager.py                   # MemoryManager，自动提取/检索/注入
│   │   └── tools.py                     # memory_save/search/list 工具
│   │
│   ├── planning/                        # 任务规划系统
│   │   ├── schema.py                    # Plan/PlanStep 模型
│   │   ├── planner.py                   # LLM 生成执行计划
│   │   ├── executor.py                  # 逐步执行计划
│   │   ├── reflector.py                 # 评估结果，决定继续/重规划
│   │   └── tools.py                     # plan_create/plan_show 工具
│   │
│   └── agents/                          # 多 Agent 协作
│       ├── base.py                      # BaseAgent 全功能基类（上下文管理+记忆注入+重试保护）
│       ├── delegate_tools.py            # 委托工具，结构化结果，持久化 thread_id
│       ├── supervisor/
│       │   ├── graph.py                 # ReAct + Plan-and-Execute 双模式编排器
│       │   └── prompts.py               # 系统提示词
│       ├── code_agent/graph.py          # CodeAgent — write→verify→fix 闭环
│       ├── research_agent/graph.py      # ResearchAgent — 多轮收集→synthesize 报告
│       └── review_agent/graph.py        # ReviewAgent — 多轮审查→结构化报告（raw LLM）
│
└── tests/                               # 测试（169 个）
    ├── conftest.py                      # 共享 fixtures
    ├── test_main.py                     # 入口测试
    ├── shared/                          # 工具/上下文/AST/MCP 测试
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

### Agent 专业化流程

| Agent | 流程图 | 特点 |
|-------|--------|------|
| **CodeAgent** | agent → tools → verify → (pass: END \| fail: agent) | write→verify→fix 闭环：语法检查→导入检查→测试运行 |
| **ResearchAgent** | agent → tools → agent → ... → synthesize → END | 多轮信息收集后强制输出结构化研究报告 |
| **ReviewAgent** | agent → tools → ... → report → END | 至少一轮工具调用后，使用 raw LLM 生成审查报告 |

### 记忆系统

基于 SQLite + FTS5，零外部依赖：

- 对话结束时自动提取值得记忆的信息
- FTS5 全文搜索 + LIKE 模糊匹配双通道检索
- 记忆注入系统提示词，提供上下文感知

### 多 Agent 协作

Supervisor 通过委托工具调度专业子 Agent：

- `delegate_to_code` — 代码生成、编辑、调试，返回结构化结果（success/summary/files_modified）
- `delegate_to_research` — 文件搜索、阅读、分析，多轮收集后自动生成报告
- `delegate_to_review` — 代码审查、安全分析、质量评估，使用 raw LLM 防止幻觉 tool_calls

### 上下文窗口管理

- **tiktoken 精确计数**：使用 `cl100k_base` 编码，回退到 CJK 感知的启发式估算
- **滑动窗口裁剪**：保留 SystemMessage + 最近 10 条消息，中间消息裁剪并插入通知
- **LLM 摘要压缩**：超过 85% 阈值触发，将旧消息压缩为 3-5 句摘要

### AST 结构化编辑

基于 tree-sitter 的字节级编辑，支持 Python：

- `ast_info` — 分析文件结构（函数/类/import）
- `ast_find` — 查找函数/类/方法/变量（精确行号）
- `ast_rename` — 语义级重命名标识符
- `ast_add_param` — 为函数添加参数
- `ast_add_method` — 为类添加方法
- `ast_add_import` — 添加 import 语句

### 安全沙箱

`run_python` 工具在隔离子进程中执行代码：

- 模块级 import 黑名单（os、subprocess、socket 等 12 个模块）
- 256MB 内存上限，watchdog 线程每 200ms 实时监控
- 可配置超时（最长 60s），防止无限循环
- 跨平台支持 Windows/Unix

## 技术栈

- Python 3.11+
- LangGraph + LangChain
- Pydantic v2（工具 Schema 和数据校验）
- tree-sitter（AST 解析）
- tiktoken（token 计数）
- SQLite + FTS5（记忆存储）
- httpx（API 请求）
- psutil（进程内存监控）
