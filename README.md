# LangCode

基于 LangGraph 构建的 AI Code Agent，对标 Claude Code 工程水准的五层架构重构。

## 核心特性

- **五层架构** — Layer 0 共享内核 → Layer 1 基础设施 → Layer 2 Agent 系统 → Layer 3 工具系统 → Layer 4 查询引擎 → Layer 5 CLI
- **1 主 + 2 子 Agent** — Supervisor 中枢路由，Explore（快速只读搜索）和 Review（代码审查）子图，纯 tool calling 驱动路由
- **auto\_verify 闭环** — 主图内联验证节点，代码修改后强制执行语法检查、导入检查、lint、测试，不靠提示词
- **ToolRegistry 工具注册中心** — 30+ 内置工具，按权限模式动态过滤，源头拦截工具可见性
- **AST 结构化编辑** — 基于 tree-sitter 的语义级代码操作，LangCode 差异化能力（Claude Code 无此项）
- **五层权限防线** — plan / accept\_edits / default / dont\_ask / bypass，RuleEngine 三层优先级规则匹配
- **QueryEngine 查询引擎** — AsyncGenerator 全链路流式管道，query\_loop 状态机（Continue/Terminal）
- **上下文管理** — 三层压缩策略（MicroCompact → AutoCompact → SnipCompact），断路器防止无限失败
- **错误恢复链** — max\_output 截断升级、413 prompt\_too\_long 压缩、模型不可用 fallback，被扣留消息延迟表面化
- **Memory 记忆系统** — SQLite + FTS5 + jieba 分词，自动提取、时间衰减、上下文注入
- **Skill 系统** — 可发现、可复用的能力包，支持 Fork 子 Agent 或内联注入执行

## 架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 5: CLI/UI 层                                              │
│  cli/commands.py  cli/repl.py                                    │
│  斜杠命令 · 流式输出 · 中断处理                                     │
├──────────────────────────────────────────────────────────────────┤
│  Layer 4: 查询引擎层                                              │
│  engine/query_engine.py  engine/query_loop.py                    │
│  engine/context.py  engine/budget.py  engine/recovery.py         │
│  会话生命周期 · 状态机 · Token预算 · 错误恢复                        │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: 工具系统层                                              │
│  tools/base.py  tools/registry.py  tools/execution.py            │
│  tools/builtin/  tools/ast/  tools/mcp/                          │
│  Tool<I,O> 泛型接口 · 注册发现 · 并发调度 · 权限检查                 │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: Agent 系统层                                            │
│  agents/definition.py  agents/graph_builder.py  agents/router.py │
│  agents/verify.py  agents/skills/                                │
│  1主+2子 · auto_verify · Skill Fork · tool calling 路由           │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1: 基础设施层                                              │
│  services/  state/  permissions/  memory/  planning/             │
│  LLM客户端 · 分层配置 · Store · Transcript · 权限引擎 · 规划       │
├──────────────────────────────────────────────────────────────────┤
│  Layer 0: 共享内核（5 文件，零业务逻辑）                             │
│  shared/types.py  shared/models.py  shared/errors.py             │
│  shared/logger.py  shared/__init__.py                            │
└──────────────────────────────────────────────────────────────────┘
```

## 项目结构

```
LangCode/
├── src/LangCode/
│   ├── main.py                          # 入口：组装全部子系统 + 启动
│   │
│   ├── shared/                          # Layer 0: 零依赖共享内核（5 文件）
│   │   ├── types.py                     # LCState TypedDict（8 个图流程字段）
│   │   ├── models.py                    # 所有 Pydantic 响应模型（13 个类型）
│   │   ├── errors.py                    # LangCodeError 异常层次
│   │   └── logger.py                    # 日志工厂
│   │
│   ├── services/                        # Layer 1a: 外部服务
│   │   ├── config.py                    # 分层配置：default → user → project → env
│   │   ├── llm.py                       # LLMClient：模型管理、thinking 剥离、fallback
│   │   └── analytics.py                 # 遥测：启动耗时、API 耗时、工具统计
│   │
│   ├── state/                           # Layer 1b: 状态管理
│   │   ├── store.py                     # Store<T>：34 行极简响应式容器
│   │   ├── app_state.py                 # AppState 结构 + Store 单例
│   │   ├── session.py                   # SessionStore：SQLite 会话元数据索引
│   │   ├── transcript.py                # Transcript：JSONL 只追加日志 + 会话恢复
│   │   └── compact.py                   # ContextCompactor：三层上下文压缩
│   │
│   ├── permissions/                     # Layer 1c: 权限系统
│   │   ├── model.py                     # 五层 PermissionMode + PermissionResult
│   │   ├── rules.py                     # RuleEngine：Allow/Deny/Ask + 三层优先级
│   │   ├── classifier.py                # BashClassifier：只读/破坏性/网络命令分类
│   │   └── sandbox.py                   # PathSandbox：工作目录锁定 + 路径边界校验
│   │
│   ├── memory/                          # Layer 1d: 记忆系统
│   │   ├── store.py                     # SQLite + FTS5 + jieba 分词 + 时间衰减
│   │   ├── manager.py                   # 自动提取 + 检索 + 上下文注入
│   │   └── tools.py                     # memory_save / memory_search / memory_list
│   │
│   ├── planning/                        # Layer 1e: 规划系统
│   │   ├── schema.py                    # Plan / PlanStep（Pydantic v2）
│   │   ├── context.py                   # PlanContextInjector：分状态注入提示词
│   │   └── todo_tools.py                # write_todo / update_todo / modify_todo
│   │
│   ├── tools/                           # Layer 3: 工具系统
│   │   ├── base.py                      # Tool<I,O> ABC：统一工具接口
│   │   ├── registry.py                  # ToolRegistry：注册 → 发现 → 过滤 → Schema
│   │   ├── context.py                   # ToolUseContext：依赖注入载体（15+ 字段）
│   │   ├── execution.py                 # StreamingToolExecutor：并发调度器
│   │   ├── builtin/                     # 内置工具（每工具一个文件，自包含）
│   │   │   ├── file_read.py             # 文本/图片/PDF/Jupyter 多格式读取
│   │   │   ├── file_write.py            # 创建文件 + 自动创建父目录
│   │   │   ├── file_edit.py             # 唯一性字符串匹配
│   │   │   ├── search.py                # GlobTool + GrepTool（ripgrep 集成）
│   │   │   ├── shell.py                 # BashTool + BashClassifier 安全分析
│   │   │   ├── python.py                # PythonTool + 沙箱 + 内存看门狗
│   │   │   ├── web.py                   # WebFetch + WebSearch
│   │   │   └── delegate.py              # delegate_explore / delegate_review
│   │   ├── ast/                         # AST 结构化编辑（LangCode 差异化）
│   │   │   ├── editor.py                # tree-sitter 核心引擎
│   │   │   ├── tools.py                 # LangChain 工具包装
│   │   │   └── languages/               # 语言插件接口
│   │   │       ├── interface.py         # LanguagePlugin ABC
│   │   │       └── python.py            # Python tree-sitter 实现
│   │   └── mcp/                         # MCP 适配器
│   │       ├── client.py                # MCP 客户端（stdio 传输）
│   │       └── adapter.py               # MCP Tool → LangCode Tool
│   │
│   ├── agents/                          # Layer 2: Agent 系统
│   │   ├── definition.py                # AgentDefinition：声明式定义（内置 2 个）
│   │   ├── graph_builder.py             # 构建 Supervisor 主图 + Explore/Review 子图
│   │   ├── router.py                    # 路由：tool_calls → 信号提取 → 四路分发
│   │   ├── verify.py                    # auto_verify：代码修改后自动验证
│   │   ├── prompts.py                   # Agent 提示词管理
│   │   ├── builtin/                     # 内置 Agent 子图
│   │   └── skills/                      # Skill 系统
│   │       ├── loader.py                # SkillLoader：从 .langcode/skills/*.md 发现
│   │       └── runner.py                # SkillRunner：Fork 子 Agent 执行
│   │
│   ├── engine/                          # Layer 4: 查询引擎
│   │   ├── query_engine.py              # QueryEngine：会话生命周期管理
│   │   ├── query_loop.py                # query_loop：API ↔ 工具执行状态机
│   │   ├── context.py                   # 系统提示组装流水线
│   │   ├── budget.py                    # BudgetTracker：Token 预算 + 收益递减
│   │   └── recovery.py                  # 错误恢复链：413 → compact → fallback
│   │
│   ├── cli/                             # Layer 5: CLI/UI
│   │   ├── commands.py                  # 斜杠命令：/mode /session /memory /todo /skills
│   │   └── repl.py                      # 命令行 REPL：AsyncGenerator 消费 + 流式输出
│   │
│   ├── resources/                       # 提示词模板
│   └── main.py                          # 入口
│
└── tests/                               # 测试
    ├── conftest.py                      # 共享 fixtures
    ├── test_main.py                     # 入口测试
    ├── shared/                          # 工具/AST/MCP 测试
    ├── memory/                          # 记忆系统测试
    ├── planning/                        # 规划系统测试
    └── agents/                          # Agent 路由和委托测试
```

## 快速开始

```bash
# 安装依赖
uv sync

# 配置 LLM（必填）
export LC_MODEL_NAME="your-model"
export LC_API_KEY="your-api-key"
export LC_BASE_URL="your-base-url"

# 运行 Agent
uv run python src/LangCode/main.py

# 运行测试
uv run pytest tests/ -v
```

### 环境变量

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `LC_MODEL_NAME` | 推荐 | LLM 模型名 | `mimo-v2.5-pro` |
| `LC_API_KEY` | 推荐 | LLM API Key | （空） |
| `LC_BASE_URL` | 推荐 | LLM API 地址 | `https://token-plan-cn.xiaomimimo.com/v1` |
| `TAVILY_API_KEY` | 可选 | 网络搜索（[注册](https://tavily.com)免费额度） | （空，未配置则 web_search 不可用） |
| `SERPAPI_API_KEY` | 可选 | 网络搜索备选（[注册](https://serpapi.com)） | （空，优先用 Tavily） |
| `LC_LOG_LEVEL` | 可选 | 日志级别（DEBUG/INFO/WARNING/ERROR） | `INFO` |
| `LC_BASH_PATH` | 可选 | Windows 下 git-bash.exe 路径 | （空，回退 cmd.exe） |

> 配置优先级：默认值 → `~/.langcode/config.json` → `.langcode/config.json` → 环境变量

## Agent 系统

### 设计原则

Agent 划分的依据是**隔离需求**，不是能力类型：

- **Token 空间隔离** — 大量中间操作不污染主对话 → 子 Agent
- **权限隔离** — 子任务需要更严格约束 → 子 Agent
- **模型降级** — 子任务不需要强模型 → 子 Agent
- **以上都不需要** — 主 Agent 直接做

### 1 主 + 2 子

| Agent | 类型 | 工具集 | 特点 |
|-------|------|--------|------|
| **Supervisor** | 主 Agent | 全部工具 | 中枢路由，纯 tool calling 驱动，直接编写代码 |
| **Explore** | 子图 | 只读工具 | Token 隔离，可降级模型，省略 CLAUDE.md |
| **Review** | 子图 | 只读工具 | Token 隔离，对抗性审查，raw LLM 生成报告 |

### 路由机制

v2 使用纯 tool calling 驱动路由（替代 v1 的文本解析）：

```
LLM tool_calls:
  plan_create       → 创建执行计划，逐步执行 + 反思
  delegate_explore  → 委派给 Explore Agent（只读搜索）
  delegate_review   → 委派给 Review Agent（代码审查）
  普通工具调用       → 主 Agent 直接执行（ReAct 循环）
```

### auto\_verify 闭环

代码修改后在主图中强制验证（不是靠提示词请求 LLM "请检查"）：

```
tools → auto_verify → (通过: router | 失败: agent 修复)
```

验证步骤：py\_compile 语法检查 → import 导入检查 → ruff lint → pytest 测试

## 查询引擎

QueryEngine 封装完整的会话生命周期：

```
submit_message(prompt)
    │
    ├── Phase 1: 上下文组装（系统提示 + 记忆 + CLAUDE.md）
    ├── Phase 2: 用户输入处理（斜杠命令 / 普通消息）
    ├── Phase 3: query_loop 状态机
    │     while True:
    │       1. 预处理：上下文压缩检查
    │       2. API 流式调用
    │       3. 无工具调用 → 完成（Terminal）
    │       4. 有工具调用 → 执行 → 继续（Continue）
    └── Phase 4: 结果汇总（用量、耗时、权限事件）
```

### 上下文压缩

三层压缩策略 + 断路器：

| 策略 | 触发条件 | 行为 |
|------|----------|------|
| **MicroCompact** | 工具输出 > 2000 字符 | 裁剪为前 2000 + 标记 |
| **AutoCompact** | token 超过阈值 | LLM 将旧消息压缩为摘要 |
| **SnipCompact** | 仍然超限 | 用文件当前状态替换历史内容 |

断路器：连续失败 3 次后停止尝试，防止浪费 API 调用。

### 错误恢复链

| 错误类型 | 恢复策略 |
|----------|----------|
| max\_output 截断 | escalate 8k → 64k → recovery message（最多 3 次） |
| 413 prompt\_too\_long | collapse drain → reactive compact → 错误表面化 |
| 模型不可用 | fallback 模型 + thinking 签名剥离 |

## 权限系统

五层权限模式：

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `plan` | 只规划不执行，仅只读工具 | 探索性任务 |
| `accept_edits` | 文件编辑自动通过，shell 需确认 | 日常开发 |
| `default` | 只读自动通过，写操作需确认 | 默认模式 |
| `dont_ask` | 遇到需确认的操作自动拒绝 | 自动化场景 |
| `bypass` | 全部自动批准 | 可信环境 |

规则引擎：policy > project > user 三层优先级，支持工具级和内容级匹配。

BashClassifier：命令语义分析，区分只读/破坏性/网络命令，检测 11 种命令替换模式。

## AST 结构化编辑

LangCode 相对于 Claude Code 的差异化能力——基于 tree-sitter 的语义级代码编辑：

| 工具 | 功能 |
|------|------|
| `ast_info` | 分析文件结构（函数/类/import） |
| `ast_find` | 查找函数/类/方法/变量（精确行号） |
| `ast_rename` | 语义级重命名（同作用域标识符） |
| `ast_add_param` | 为函数添加参数（自动处理 self/cls） |
| `ast_add_method` | 为类添加方法（自动处理缩进） |
| `ast_add_import` | 添加 import 语句（避免重复） |

支持 LanguagePlugin ABC 扩展点，当前实现 Python，未来可扩展 TS/Go/Rust。

## 配置

分层配置优先级（低 → 高）：

1. **CONFIG\_DEFAULTS** — 代码硬编码
2. **user\_config** — `~/.langcode/config.json`
3. **project\_config** — `.langcode/config.json`
4. **env\_vars** — `LC_MODEL_NAME`、`LC_API_KEY`、`LC_BASE_URL` 等

```python
CONFIG_DEFAULTS = {
    "model.name": "mimo-v2.5-pro",
    "model.temperature": 0,
    "session.max_turns": 50,
    "permission.mode": "default",
    "verify.auto_enabled": True,
}
```

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/mode <plan\|build>` | 切换权限模式 |
| `/session list\|new\|<id>` | 会话管理 |
| `/memory search <query>` | 搜索记忆 |
| `/todo show` | 查看当前计划 |
| `/skills list` | 列出可用 Skill |

## 技术栈

- Python 3.11+
- LangGraph + LangChain
- Pydantic v2（工具 Schema 和数据校验）
- tree-sitter（AST 解析）
- SQLite + FTS5（记忆存储、会话存储、Checkpoint）
- httpx（API 请求）
- psutil（进程内存监控）

## 设计文档

完整架构设计见 [ARCHITECTURE_v2.md](./ARCHITECTURE_v2.md)，包含：

- 五层架构详细设计与层间依赖规则
- Plan 生命周期全流程（创建 → 执行 → 反思 → 完成）
- Agent Delegation 全流程（tool calling → 子图 → 结构化摘要返回）
- 上下文压缩全流程（Micro → Auto → Snip 三层策略）
- 错误恢复链完整决策树
- 与 Claude Code 的 30+ 维度完整对比
