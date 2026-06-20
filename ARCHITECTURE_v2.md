# LangCode v2.1 — 最终架构设计文档

> 对标 Claude Code v2.1.x 源码拆解，基于 LangCode 现有代码资产的全面重构方案。
>
> v2.1 变更（2026-06-20）：工具系统简化、控制流反转修复、L2→L3 依赖消除。详见 [附录 A](#附录-a-v21-变更日志)。

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [整体分层与模块清单](#2-整体分层与模块清单)
3. [Layer 0: shared — 最小化共享内核](#3-layer-0-shared)
4. [Layer 1: services / state / permissions / memory / planning](#4-layer-1-基础设施层)
5. [Layer 2: agents — Agent 系统（核心重构）](#5-layer-2-agent-系统)
6. [Layer 3: tools — 工具系统](#6-layer-3-工具系统)
7. [Layer 4: engine — 查询引擎](#7-layer-4-查询引擎)
8. [Layer 5: cli — CLI/UI 层](#8-layer-5-cliui-层)
9. [Plan 生命周期全流程](#9-plan-生命周期全流程)
10. [Agent Delegation 全流程](#10-agent-delegation-全流程)
11. [Agent 划分原则与设计理由](#11-agent-划分原则与设计理由)
12. [上下文压缩全流程](#12-上下文压缩全流程)
13. [错误恢复链](#13-错误恢复链)
14. [工程品质保障](#14-工程品质保障)
15. [实施路线图](#15-实施路线图)
16. [与 Claude Code 的完整对比](#16-与-claude-code-的完整对比)

---

## 1. 设计目标与原则

### 1.1 目标

将 LangCode 从"学习项目级 Agent"升级为"生产级 Code Agent CLI"，对标 Claude Code 的工程水准，同时保留 AST 编辑、自动验证闭环等差异化能力。

### 1.2 六条核心原则（提炼自 Claude Code 工程哲学）

| # | 原则 | 含义 | 在 LangCode v2 中的体现 |
|---|------|------|------------------------|
| 1 | **安全优先** | 安全是设计的起点，不是事后补丁。默认拒绝。 | 五层权限防线；Tool ABC 自包含 check_permissions；Bash 命令语义分析 |
| 2 | **渐进式复杂性** | 34行 Store 够用时绝不引入框架。每一层只加它负责的复杂性。 | Store (34行) → AppState → Compact → Engine；每层独立 |
| 3 | **AsyncGenerator 管道** | 全链路流式传递：背压控制 + 惰性计算 + 流式渲染 | QueryEngine.submit_message() → query_loop() → call_model() |
| 4 | **失败关闭** | 不确定时选择更安全的默认值。安全检查只能升级不能降级。 | PermissionMode 默认 "default"；断路器限制 3 次连续失败 |
| 5 | **数据驱动** | 用遥测数据指导优化，不靠猜测。 | AnalyticsSnapshot + 关键路径计时 + Token 消耗追踪 |
| 6 | **可组合性胜过单体** | 小可组合原语 > 大不可分割框架 | Store + onChange + Selector；AsyncGenerator 组合；Tool 接口组合 |

### 1.3 五条生产级 Agent 工程法则

对标 Claude Code 第 25 章的工程法则，LangCode v2 的设计同样遵循：

1. **永远假设会崩溃** — Transcript JSONL 只追加写入；checkpoint 自动持久化全部状态；断路器防止无限重试
2. **非确定性是常态** — 权限系统不依赖模型"承诺"；Reflector 使用 structured output 而非自由文本；错误恢复链处理 API 随机失败
3. **成本是一等约束** — BudgetTracker 检测收益递减；MicroCompact 裁剪工具输出；Explore Agent 可降级模型
4. **上下文是最宝贵的资源** — 系统提示精确注入（非全量 CLAUDE.md）；三层压缩策略（Micro → Auto → Snip）；Explore 省略项目上下文
5. **用户信任最难获得也最易失去** — 权限默认需要确认；操作全程透明展示；支持 Escape 取消；Transcript 支持恢复

---

## 2. 整体分层与模块清单

### 2.1 五层架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 5: CLI/UI 层                                              │
│  cli/commands.py  cli/repl.py  cli/tui/                          │
│  斜杠命令 · 流式输出 · TUI 响应式 UI · 中断处理                     │
├──────────────────────────────────────────────────────────────────┤
│  Layer 4: 查询引擎层  ★ 核心创新                                  │
│  engine/query_engine.py  engine/query_loop.py                    │
│  engine/context.py  engine/budget.py  engine/recovery.py         │
│  会话生命周期 · 状态机(Continue/Terminal) · Token预算 · 错误恢复    │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: 工具系统层                                              │
│  tools/base.py  tools/registry.py  tools/execution.py            │
│  tools/builtin/  tools/ast/  tools/mcp/                           │
│  Tool<I,O> 泛型接口 · 注册发现 · 并发调度 · 权限检查 · AST编辑      │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: Agent 系统层  ★ 核心重构                                │
│  agents/definition.py  agents/supervisor.py  agents/router.py    │
│  agents/verify.py  agents/builtin/  agents/skills/                │
│  1主+2子 · auto_verify · Skill Fork · 只返回结构化摘要             │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1: 基础设施层                                              │
│  services/  state/  permissions/  memory/  planning/             │
│  LLM客户端 · 分层配置 · Store · Transcript · 权限引擎 · 规划       │
├──────────────────────────────────────────────────────────────────┤
│  Layer 0: 共享内核 (5文件，零业务逻辑)                              │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 完整目录结构

```
src/LangCode/
│
├── shared/                     # Layer 0: 零依赖共享内核（5文件）
│   ├── __init__.py
│   ├── types.py                # LCState TypedDict（8字段，仅图流程相关）
│   ├── models.py               # 所有 Pydantic 响应模型
│   ├── errors.py               # LangCodeError 异常层次
│   └── logger.py               # 日志工厂 (仅依赖 stdlib)
│
├── services/                   # Layer 1a: 外部服务
│   ├── __init__.py
│   ├── llm.py                  # LLMClient: 模型管理、thinking剥离、fallback
│   ├── config.py               # 分层配置: default → user → project → env
│   └── analytics.py            # 遥测: 启动耗时、API耗时、工具统计、Token追踪
│
├── state/                      # Layer 1b: 状态管理
│   ├── __init__.py
│   ├── store.py                # Store<T>: 34行极简响应式容器
│   ├── app_state.py            # AppState 结构 + 默认值 + Store单例
│   ├── session.py              # Transcript: JSONL 只追加日志 + 会话恢复
│   └── compact.py              # ContextCompactor: Micro→Auto→Snip 三层压缩
│
├── permissions/                # Layer 1c: 权限系统
│   ├── __init__.py
│   ├── model.py                # 五层 PermissionMode + PermissionResult
│   ├── rules.py                # RuleEngine: Allow/Deny/Ask + policy>project>user
│   ├── classifier.py           # BashClassifier: 只读/破坏性/网络 命令分类
│   └── sandbox.py              # PathSandbox: 工作目录锁定 + 路径边界校验
│
├── memory/                     # Layer 1d: 记忆系统
│   ├── __init__.py
│   ├── store.py                # SQLite + FTS5 + jieba分词 + 时间衰减
│   ├── manager.py              # 自动提取 + 检索 + 上下文注入
│   └── tools.py                # memory_save / memory_search / memory_list
│
├── planning/                   # Layer 1e: 规划系统
│   ├── __init__.py
│   ├── schema.py               # Plan, PlanStep (Pydantic v2)
│   ├── planner.py              # plan_create 工具定义
│   ├── context.py              # PlanContextInjector: 分状态注入提示词
│   └── reflector.py            # ReflectDecision structured output
│
├── tools/                      # Layer 3: 工具系统
│   ├── __init__.py
│   ├── base.py                 # ToolResult: 工具执行结果封装（v2.1: 删除 Tool ABC）
│   ├── registry.py             # ToolRegistry: 注册→过滤→Schema (v2.1: ToolEntry + tags)
│   ├── context.py              # ToolUseContext: 依赖注入载体（15+字段）
│   ├── execution.py            # StreamingToolExecutor: queued→executing→completed→yielded
│   ├── result.py               # ToolResult<T> + context_modifier
│   └── builtin/                # 内置工具（每工具一个文件，自包含）
│       ├── __init__.py
│       ├── file_read.py        # FileReadTool: 文本/图片/PDF/Jupyter
│       ├── file_write.py       # FileWriteTool: 创建+父目录
│       ├── file_edit.py        # FileEditTool: 唯一性字符串匹配
│       ├── search.py           # GlobTool + GrepTool: ripgrep集成
│       ├── shell.py            # BashTool + BashClassifier
│       ├── python.py           # PythonTool + 沙箱 + 内存看门狗
│       ├── web.py              # WebFetch + WebSearch
│       └── git.py              # GitStatus/Diff/Log/Blame（新增）
│       └── plan.py             # plan_create 工具（新增）
│
├── tools/ast/                  # AST 结构化编辑 ★ LangCode 差异化功能
│   ├── __init__.py
│   ├── editor.py               # tree-sitter 核心引擎
│   ├── tools.py                # LangChain 工具包装
│   └── languages/
│       ├── __init__.py
│       ├── interface.py         # LanguagePlugin ABC
│       └── python.py           # Python tree-sitter 实现
│
├── tools/mcp/                  # MCP 适配器
│   ├── __init__.py
│   ├── client.py               # MCP 客户端 (stdio/SSE transport)
│   └── adapter.py              # MCP Tool → LangCode Tool
│
├── agents/                     # Layer 2: Agent 系统 ★ 核心重构
│   ├── __init__.py
│   ├── definition.py           # AgentDefinition: 声明式定义
│   ├── supervisor.py           # Supervisor: 主图构建（6节点）
│   ├── router.py               # 路由决策: tool_calls→信号提取→四路分发
│   ├── verify.py               # auto_verify: 代码修改后自动验证
│   ├── prompts.py              # 从 resources/prompts/ 加载提示词
│   ├── builtin/                # 内置 Agent 子图（仅2个）
│   │   ├── __init__.py
│   │   ├── explore.py          # ExploreAgent: 快速只读搜索 + summarize
│   │   └── review.py           # ReviewAgent: 代码审查 + report(raw LLM)
│   └── skills/                 # Skill 系统
│       ├── __init__.py
│       ├── loader.py           # SkillLoader: 从 .langcode/skills/*.md 发现
│       └── runner.py           # SkillRunner: Fork 子Agent 执行
│
├── engine/                     # Layer 4: 查询引擎 ★ 核心创新
│   ├── __init__.py
│   ├── query_engine.py         # QueryEngine: 一个对话一个实例
│   ├── query_loop.py           # query_loop: API↔工具执行状态机
│   ├── context.py              # 系统提示组装流水线
│   ├── budget.py               # BudgetTracker: Token预算 + 收益递减
│   └── recovery.py             # 错误恢复链: 413→collapse→compact→降级
│
├── cli/                        # Layer 5: CLI/UI
│   ├── __init__.py
│   ├── commands.py             # 斜杠命令: /mode /session /memory /plan /skills
│   ├── repl.py                 # 命令行 REPL: AsyncGenerator 消费 + 流式输出
│   └── tui/                    # Textual TUI
│       ├── __init__.py
│       ├── app.py              # LangCodeTUI
│       ├── bridge.py           # AgentBridge (asyncio.Queue事件桥)
│       └── widgets/            # UI 组件
│
├── main.py                     # 入口: 组装全部子系统 + 启动 (<80行)
│
└── resources/
    └── prompts/                # 提示词模板 (Markdown)
        ├── base.md
        ├── platform_windows.md
        ├── platform_linux.md
        ├── agents/
        │   ├── supervisor.md
        │   ├── explore.md
        │   └── review.md
        └── skills/
            ├── code-review.md
            ├── refactor.md
            └── write-tests.md
```

### 2.3 层间依赖规则

```
Layer 5 ─────► Layer 4 ──► Layer 3 ──► Layer 2
   │              │            │           │
   ▼              ▼            ▼           ▼
       Layer 1 (模块间互不import)
   │              │            │           │
   ▼              ▼            ▼           ▼
            Layer 0 (所有层可import)
```

### 2.4 v1 → v2 核心差异

| 维度 | v1 现状 | v2 目标 |
|------|---------|---------|
| shared/ 文件数 | 17（垃圾场） | 5（最小化） |
| Agent 数量 | 4 (code/research/review + supervisor) | 1 主 + 2 子 (Explore/Review) |
| Code Agent | 独立子图 | **去掉**，合并到主Agent + auto_verify |
| 验证闭环 | CodeAgent 独有 | **提升到主图**，所有代码路径强制执行 |
| LCState 字段 | 17（职责爆炸） | 8（仅图流程相关） |
| 权限模式 | 2 (plan/build) | 5 (plan/acceptEdits/default/dontAsk/bypass) |
| 上下文管理 | sliding window | 三层压缩：Micro → Auto → Snip |
| 会话持久化 | SessionStore 独立 | Transcript JSONL 统一 |
| 查询引擎 | main.py 手动 stream | QueryEngine 封装完整生命周期 |
| 路由触发 | 文本解析 + tool calling 混用 | 纯 tool calling（plan_create/delegate_*） |
| 子图结果 | 全部消息追加 | 只有结构化摘要进入父图 |

---

## 3. Layer 0: shared — 最小化共享内核

### 设计原则

**只放零业务逻辑、被所有层安全 import、不产生循环依赖的内容。总共 5 个文件。**

### 3.1 shared/types.py — LCState 类型定义

```python
"""全局类型定义：LCState。零业务逻辑，所有模块可安全 import。"""

from typing import Literal, Annotated, Optional, TypedDict
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


def _last_wins(_old, new):
    """Reducer: 多节点同时更新同一 key 时取最后值"""
    return new


class LCState(TypedDict):
    """LangGraph 图流程状态 — 仅包含图表流转所需的字段

    设计原则：
    - 只放图流程相关字段（路由信号、跨节点通信、图执行上下文）
    - 用户偏好、模式配置、统计 → AppState (Store)
    - 每个字段有明确的"设置者"和"消费者"
    - 从 v1 的 17 个字段精简到 8 个
    """

    # ── 对话核心 ──
    # 设置者: agent + tools + 用户入口  消费者: 所有 LLM 调用
    messages: Annotated[list[AnyMessage], add_messages]

    # ── 路由信号（瞬态：设置后立即消费，不跨轮次）──
    # 设置者: router.process_tool_results
    # 消费者: router.after_tools_routing
    route: Annotated[str, _last_wins]

    # ── 计划上下文（生命周期: plan_create → plan_complete/abandon）──
    # 设置者: router.process_tool_results
    # 消费者: supervisor._call_llm (注入) + reflector (评估) + _after_reflect (路由)
    current_plan: Optional[dict]

    # ── 子Agent 通信 ──
    # 设置者: router.process_tool_results（delegate_* 工具调用时）
    # 消费者: supervisor._delegate_router（构建子Agent 输入消息）
    task_description: str

    # ── 验证闭环 ──
    # 设置者: supervisor._auto_verify（工具执行后、router 之前）
    # 消费者: supervisor._after_verify（路由回 agent 或继续）
    verify_errors: Annotated[Optional[list[str]], _last_wins]

    # ── 记忆上下文 ──
    # 设置者: cli（每轮对话前从 MemoryManager 检索）
    # 消费者: supervisor._call_llm（注入到 LLM 消息）
    memory_context: str

    # ── 迭代控制 ──
    # 设置者: after_tools_routing（回环时 +1）
    # 消费者: router（防止死循环，> MAX_ITERATIONS → END）
    supervisor_iterations: Annotated[int, _last_wins]
```

**从 v1 移除的 10 个字段：**

| 字段 | 新位置 | 原因 |
|------|--------|------|
| user_name | AppState.user | 用户偏好，非图流程 |
| platform | AppState.user | 平台信息，非图流程 |
| current_agent | 运行时局部变量 | 仅事件渲染用，不需持久化 |
| agent_mode | AppState.session | 模式配置，节点通过 Store 读取 |
| dangerous_edit_mode | 去掉 | v2 用权限系统替代 |
| strict_mode | 去掉 | v2 用 permissions 替代 |
| content_generation_count | AppState.analytics | 纯统计用途 |
| tool_calls_count | AppState.analytics | 纯统计用途 |
| code_generation_count | AppState.analytics | 纯统计用途 |
| plan_steps | 去掉 | current_plan.steps 已包含 |
| tool_retry_count | 去掉 | v2 由 engine/recovery 管理 |

### 3.2 shared/models.py

从现有 `shared/schemas.py` 整体迁入。所有工具的 Pydantic 响应模型定义在此：
- FileContentResponse, WriteResponse, EditResponse, SearchResponse
- CommandResponse, PythonResponse, FetchAPIResponse
- GitStatusResponse, GitDiffResponse, GitLogResponse, GitBlameResponse (新增)
- AstInfoResponse, AstFindResponse, AstEditResponse

### 3.3 shared/errors.py

```python
class LangCodeError(Exception):
    """所有 LangCode 异常的基类"""
    def __init__(self, message: str, *,
                 recoverable: bool = False,
                 retry_after_ms: int = 0):
        self.recoverable = recoverable
        self.retry_after_ms = retry_after_ms

class ToolExecutionError(LangCodeError):
    tool_name: str

class PermissionDeniedError(LangCodeError):
    tool_name: str
    mode: str
    reason: str

class ContextOverflowError(LangCodeError):
    token_count: int
    max_tokens: int

class APIRateLimitError(LangCodeError): ...
class ModelUnavailableError(LangCodeError): ...
class ConfigLoadError(LangCodeError): ...
class CircuitBreakerOpen(LangCodeError): ...  # 断路器触发
```

### 3.4 shared/logger.py

保持现有一致，无变更：日志流到 stderr，级别由 `LC_LOG_LEVEL` 环境变量控制。

---

## 4. Layer 1: 基础设施层

### 4.1 state/store.py — 极简响应式容器

参考 Claude Code `createStore` 的 34 行实现：

```python
"""Store<T> — 极简响应式状态容器。34 行精华。

设计决策（参考 Claude Code store.ts）：
- 函数式更新器: setState((prev) => next) 避免丢失更新
- is 相等性检查: 避免不必要的通知（非 deep equality）
- onChange 全局回调: 副作用系统的扩展点（同步到磁盘等）
- Set 作为监听器容器: O(1) 删除，防重复
"""

from typing import TypeVar, Callable, Generic

T = TypeVar("T")
Listener = Callable[[], None]

class Store(Generic[T]):
    """响应式状态容器 — Zustand 的极简子集"""
    def get_state(self) -> T: ...
    def set_state(self, updater: Callable[[T], T]) -> None: ...
    def subscribe(self, listener: Listener) -> Callable[[], None]: ...

def create_store(initial_state: T, on_change=None) -> Store[T]:
    state = initial_state
    listeners: set[Listener] = set()

    def get_state(): return state

    def set_state(updater):
        nonlocal state
        prev = state
        next_state = updater(prev)
        if next_state is prev:  # 使用 is 而非 ==，避免 deep equality 成本
            return
        state = next_state
        if on_change:
            on_change(new_state=next_state, old_state=prev)
        for listener in listeners:
            listener()

    def subscribe(listener):
        listeners.add(listener)
        return lambda: listeners.discard(listener)

    return Store(get_state, set_state, subscribe)
```

### 4.2 state/app_state.py — 全局 AppState

```python
"""AppState — 全局应用状态，独立于 LangGraph 图流程。

域划分（参考 Claude Code AppState）：
  user:      用户信息（名称、平台、home目录）
  session:   会话配置（agent_mode, model, max_turns, auto_verify...）
  analytics:  遥测统计（工具调用次数、API耗时、Token用量...）

与 LCState 的关系：
  LCState: 图流程状态（messages, route, current_plan...）— 由 LangGraph checkpoint 持久化
  AppState: 应用配置状态 — 由 Store + Config 管理，可选择性持久化到 config.json
"""

@dataclass
class UserInfo:
    name: str = ""
    platform: Literal["windows", "linux", "mac"] = "linux"
    home_dir: str = ""

@dataclass
class SessionConfig:
    agent_mode: str = "default"       # PermissionMode
    main_loop_model: str = ""
    fast_mode: bool = False
    max_turns: int = 50
    token_budget: int | None = None
    workspace_dir: str = ""
    auto_verify: bool = True          # ★ 代码修改后自动验证

@dataclass
class AnalyticsSnapshot:
    """遥测快照 — 参考 Claude Code bootstrap/state.ts 的统计字段"""
    session_started_at: str = ""
    total_tool_calls: int = 0
    total_api_calls: int = 0
    total_api_duration_ms: int = 0
    total_tool_duration_ms: int = 0
    total_tokens_used: int = 0
    code_generation_count: int = 0

@dataclass
class AppState:
    user: UserInfo = field(default_factory=UserInfo)
    session: SessionConfig = field(default_factory=SessionConfig)
    analytics: AnalyticsSnapshot = field(default_factory=AnalyticsSnapshot)


# 全局 Store 单例 — 在 main.py 中初始化
_app_state_store: Store[AppState] = None

def init_app_state(config: "Config") -> AppState:
    """从分层 Config 加载初始 AppState"""
    ...

def get_app_state() -> AppState:
    """图节点通过此函数读取 AppState（而非从 LCState 读取）"""
    return _app_state_store.get_state()

def update_app_state(updater: Callable[[AppState], AppState]) -> None:
    _app_state_store.set_state(updater)
```

### 4.3 state/session.py — Transcript 持久化

完整参考 Claude Code transcript 机制：

```python
"""Transcript — 基于 JSONL 只追加日志的会话持久化。

参考 Claude Code:
- 只追加写入 (append-only)，崩溃安全。JSONL 格式保证即使进程崩溃也不损坏已有数据。
- parent_uuid 字段形成消息链，支持分支会话（sidechain）。
- 恢复时从最新叶节点沿 parent_uuid 回溯重建主链。
- 每 session 一个 JSONL 文件。

路径: ~/.langcode/sessions/{session_id}.jsonl

与 v1 SessionStore 的差异:
  v1: SessionStore 只存元数据（id, title, timestamp），消息由 checkpoint 管理
  v2: Transcript 存消息全文（JSONL），与 checkpoint 互补
       - Transcript: 消息历史、会话列表、跨会话搜索
       - Checkpoint: 图状态（LCState）、断点恢复
"""

class TranscriptWriter:
    """JSONL 只追加写入器"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.file_path = Path.home() / ".langcode" / "sessions" / f"{session_id}.jsonl"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, message: BaseMessage, parent_uuid: str | None = None) -> str:
        """追加一条消息。返回新生成的 UUID。"""
        ...

class TranscriptReader:
    """从 JSONL 恢复会话"""
    def load(self, session_id: str) -> list[BaseMessage]:
        """找到最新叶节点 → 沿 parent_uuid 回溯 → 构建消息链"""
        ...

    def list_sessions(self, workspace: str = "", limit: int = 20) -> list[SessionMeta]:
        """列出会话：按最后修改时间倒序"""
        ...

    def delete(self, session_id: str) -> bool: ...


@dataclass
class SessionMeta:
    id: str
    title: str          # 从第一条用户消息提取（前60字符）
    message_count: int
    created_at: str
    updated_at: str
    workspace: str
```

### 4.4 state/compact.py — 上下文压缩

完整参考 Claude Code 的三层压缩策略：

```python
"""ContextCompactor — 三层上下文压缩策略。

参考 Claude Code:
  1. MicroCompact: 裁剪单条过长工具输出（> 2000字符 → 2000 + 标记）
  2. AutoCompact: LLM 生成对话摘要（System + 摘要 + 最近N条）
  3. SnipCompact: 基于文件当前状态替换历史内容

阈值计算:
  effectiveWindow = contextWindow - maxOutputTokens (为输出预留空间)
  autoCompactThreshold = effectiveWindow - AUTOCOMPACT_BUFFER (13,000 tokens)

断路器:
  连续失败 3 次 → 停止尝试。参考 Claude Code 真实数据：
  "BQ 2026-03-10: 1,279 sessions had 50+ consecutive failures"
"""

# 常量（对齐 Claude Code）
AUTOCOMPACT_BUFFER_TOKENS = 13_000
WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
MAX_CONSECUTIVE_COMPACT_FAILURES = 3

# 可压缩的工具列表（输出通常很长且后续不再需要）
COMPACTABLE_TOOLS = frozenset({
    "read_file", "execute_shell", "search_files",
    "fetch_api", "run_python",
    "write_file", "edit_file",
})


@dataclass
class CompactDecision:
    should_compact: bool
    reason: str          # "above_threshold" | "user_requested" | "approaching_limit"
    token_count: int
    threshold: int

@dataclass
class CompactResult:
    was_compacted: bool
    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int
    strategy: str        # "micro" | "auto" | "snip"


class ContextCompactor:
    def __init__(self, llm, model_name: str):
        self.llm = llm
        self.model_name = model_name
        self.consecutive_failures = 0

    def should_compact(self, messages: list, token_count: int) -> CompactDecision:
        threshold = self._get_auto_compact_threshold()
        return CompactDecision(
            should_compact=token_count > threshold,
            reason="above_threshold" if token_count > threshold else "below_threshold",
            token_count=token_count,
            threshold=threshold,
        )

    def micro_compact(self, messages: list) -> list:
        """MicroCompact: 裁剪过长的工具输出。

        规则（参考 Claude Code time-based microCompact）：
        - 工具输出 > 2000 字符 → 裁剪到前 2000 + "[Old tool result content cleared]"
        - 保留错误信息完整（错误可能包含关键调试信息）
        - 只处理 COMPACTABLE_TOOLS 中的工具
        - 保留最近 N 条消息不裁剪
        """
        ...

    def auto_compact(self, messages: list) -> CompactResult:
        """AutoCompact: LLM 摘要压缩。

        流程:
        1. 分离: System消息 + 最近10条 + 其余
        2. 调用 LLM 将"其余"压缩为 3-5 句摘要
        3. 组装: System + 摘要（SystemMessage）+ 最近消息
        4. 如果失败 → consecutive_failures += 1

        断路器:
        if consecutive_failures >= 3: 跳过压缩
        """
        if self.consecutive_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
            return CompactResult(was_compacted=False, ...)
        ...

    def snip_compact(self, messages: list, file_cache: dict) -> CompactResult:
        """SnipCompact: 用文件当前状态替换历史内容。

        适用于: 大量 file_read 结果占据了历史对话。
        将引用替换为 "File X has current content: ..." 替代完整历史内容。
        """
        ...

    def _get_effective_window(self) -> int:
        context_window = get_context_window_for_model(self.model_name)
        return context_window - MAX_OUTPUT_TOKENS_FOR_SUMMARY

    def _get_auto_compact_threshold(self) -> int:
        return self._get_effective_window() - AUTOCOMPACT_BUFFER_TOKENS
```

### 4.5 permissions/ — 权限系统

#### 4.5.1 permissions/model.py

```python
"""权限模型 — 五层模式 + 三元决策

参考 Claude Code 六层权限模式（去掉 auto，因为需要 AI 分类器）。
"""

PermissionMode = Literal[
    "plan",           # 只规划不执行：仅只读工具
    "accept_edits",   # 文件编辑自动通过，shell 需确认
    "default",        # 只读自动通过，写操作需确认（默认模式）
    "dont_ask",       # 遇到需确认的操作自动拒绝
    "bypass",         # 全部自动批准
]

PermissionBehavior = Literal["allow", "deny", "ask"]

class PermissionResult:
    behavior: PermissionBehavior
    reason: str = ""
    requires_user_confirmation: bool = False

    @classmethod
    def allow(cls, reason=""): ...
    @classmethod
    def deny(cls, reason): ...
    @classmethod
    def ask(cls, reason): ...
```

#### 4.5.2 permissions/rules.py

```python
"""RuleEngine — 三层优先级规则匹配引擎

参考 Claude Code 权限规则系统:
  - 多个来源: policy > project > user（由 SettingsSource 层级决定）
  - 工具匹配: toolName 精确匹配 + ruleContent 内容级匹配
  - 扁平化: 所有来源的 allow/deny/ask 规则分别扁平化

规则格式:
  {
    "tool": "Bash(git push*)" | "FileWrite" | "*",
    "behavior": "allow" | "deny" | "ask"
  }
"""

class PermissionRule:
    source: str          # "policy" | "project" | "user"
    tool_pattern: str    # "Bash" | "Bash(git:*)" | "FileWrite" | "*"
    rule_content: str = ""  # 内容级匹配（如 "git push*"）
    behavior: PermissionBehavior

class RuleEngine:
    def __init__(self):
        self._rules: list[PermissionRule] = []

    def load_rules(self, workspace_dir: str):
        """从三层配置加载规则: policy → project → user"""
        ...

    def evaluate(self, tool_name: str, tool_args: dict,
                 context: "ToolUseContext") -> PermissionResult:
        """按优先级评估: policy > project > user > default fallback.

        匹配逻辑（参考 Claude Code toolMatchesRule）:
        1. rule_content 为空 → 匹配整个工具
        2. rule_content 非空 → 匹配工具+内容
        3. 无匹配规则 → 根据 permission_mode 返回默认行为
        """
        mode = context.permission_mode
        # plan 模式下所有写操作直接 deny
        if mode == "plan" and not self._is_read_only_tool(tool_name):
            return PermissionResult.deny("plan 模式禁止写操作")
        # 按优先级匹配规则
        for rule in sorted(self._rules, key=lambda r: _source_priority(r.source)):
            if self._matches(rule, tool_name, tool_args):
                return PermissionResult(behavior=rule.behavior,
                                       reason=f"matched {rule.source} rule: {rule.tool_pattern}")
        # 默认行为
        return self._default_behavior(mode, tool_name, tool_args)

    def _matches(self, rule: PermissionRule, tool_name: str, args: dict) -> bool: ...
    def _default_behavior(self, mode: str, tool_name: str, args: dict) -> PermissionResult: ...
```

#### 4.5.3 permissions/classifier.py

```python
"""BashClassifier — 命令语义分析器

参考 Claude Code bashSecurity.ts 和 readOnlyValidation.ts:
- 引号内容提取（三种视图: withDoubleQuotes, fullyUnquoted, unquotedKeepQuoteChars）
- 命令替换模式检测（$(), <(), =(), ${}, $[], ~[]... 共 11 种）
- 破坏性命令检测（rm, mv, dd, shred, truncate, mkfs...）
- 只读命令白名单（ls, cat, grep, find, git...）
- 网络命令检测（curl, wget, nc...）
"""

class BashClassifier:
    # 只读命令白名单
    READ_ONLY_COMMANDS = frozenset({
        "ls", "cat", "head", "tail", "less", "more",
        "grep", "rg", "find", "wc", "stat", "file",
        "which", "whereis", "echo", "printf", "date",
        "pwd", "env", "printenv", "uname", "whoami", "id",
        "git", "hg", "svn",       # VCS（另有子命令级别检查）
        "jq", "awk", "cut", "sort", "uniq", "tr",
        "sed", "diff", "cmp", "comm",
    })

    # 破坏性命令
    DESTRUCTIVE_COMMANDS = frozenset({
        "rm", "mv", "cp", "dd", "shred", "truncate",
        "mkfs", "format", "fdisk", "parted",
        "chmod", "chown", "chgrp",
        "kill", "killall", "pkill",
    })

    # 网络命令
    NETWORK_COMMANDS = frozenset({
        "curl", "wget", "nc", "netcat", "ncat",
        "ssh", "scp", "sftp", "rsync", "telnet",
    })

    # 命令替换模式（参考 Claude Code COMMAND_SUBSTITUTION_PATTERNS）
    SUBSTITUTION_PATTERNS = [
        (r"<\(",   "process substitution <()"),
        (r">\(",   "process substitution >()"),
        (r"\$\(",  "$() command substitution"),
        (r"\$\{",  "${} parameter substitution"),
        (r"\$\[",  "$[] legacy arithmetic expansion"),
    ]

    def is_read_only(self, command: str) -> bool: ...
    def is_destructive(self, command: str, cwd: str) -> bool: ...
    def is_network(self, command: str) -> bool: ...
    def get_working_dirs(self, command: str) -> list[str]: ...
    def validate_paths(self, command: str, allowed_dirs: set[str]) -> list[Violation]: ...

    def _parse_command_chain(self, command: str) -> list[dict]:
        """解析复合命令（管道 `|`、条件 `&&` `||`、分隔 `;`）"""
        ...

    def _extract_command_name(self, cmd: str) -> str:
        """从可能包含路径和参数的命令字符串中提取命令名"""
        ...
```

#### 4.5.4 permissions/sandbox.py

```python
"""PathSandbox — 工作目录锁定 + 路径边界校验

参考 Claude Code pathValidation.ts:
- 所有文件操作必须在 allowed_dirs 范围内
- 解析符号链接后再检查边界
- additional_working_directories 支持多工作区
"""

class PathSandbox:
    def __init__(self, workspace_dir: str,
                 additional_dirs: list[str] | None = None):
        self.allowed_dirs: set[str] = {workspace_dir}
        if additional_dirs:
            self.allowed_dirs.update(additional_dirs)

    def is_path_allowed(self, path: str) -> bool:
        """检查路径是否在允许的目录树内（解析符号链接后）"""
        ...

    def resolve_safe_path(self, raw_path: str) -> str | None:
        """解析路径，如果越界返回 None"""
        ...

    def validate_file_operation(self, operation: str, path: str) -> tuple[bool, str]:
        """验证文件操作。返回 (is_safe, reason)"""
        ...
```

### 4.6 services/config.py — 分层配置

```python
"""分层配置系统。

优先级（低→高）参考 Claude Code:
  1. CONFIG_DEFAULTS   — 代码硬编码
  2. user_config       — ~/.langcode/config.json
  3. project_config    — .langcode/config.json
  4. env_vars          — 环境变量覆盖

配置 key 示例:
  model.name, model.api_key, model.base_url, model.temperature
  session.max_turns, session.token_budget
  permission.mode
  verify.auto_enabled, verify.run_tests
"""

CONFIG_DEFAULTS = {
    "model.name": "mimo-v2.5-pro",
    "model.temperature": 0,
    "session.max_turns": 50,
    "session.token_budget": None,
    "permission.mode": "default",
    "verify.auto_enabled": True,
    "verify.run_tests": True,
    "context.max_tokens": 80_000,
}

class Config:
    @classmethod
    def load(cls, workspace_dir: str | None = None) -> "Config": ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def get_model(self) -> dict:
        """获取模型配置，包含别名解析"""
        ...
    def get_permission_rules(self) -> list[dict]: ...
```

### 4.7 services/llm.py — LLM 客户端

```python
"""LLMClient — 模型管理、thinking签名剥离、动态工具绑定。

参考 Claude Code services/api/:
- 模型切换: 主模型 → fallback 自动降级
- thinking 签名剥离: 降级到不支持 thinking 的模型时，剥离 protected thinking blocks
  "Thinking signatures are model-bound: replaying a protected-thinking block
   to an unprotected fallback 400s."
- 动态工具绑定: 每次 _call_llm 根据 agent_mode 绑定工具子集
"""

class LLMClient:
    def __init__(self, config: Config):
        model_cfg = config.get_model()
        self.primary_model = ChatOpenAI(
            model=model_cfg["name"],
            api_key=model_cfg["api_key"],
            base_url=model_cfg["base_url"],
            temperature=model_cfg["temperature"],
        )
        self.fallback_model: ChatOpenAI | None = None
        fallback_name = config.get("model.fallback")
        if fallback_name:
            self.fallback_model = ChatOpenAI(
                model=fallback_name,
                api_key=model_cfg["api_key"],
                base_url=model_cfg["base_url"],
                temperature=0,
            )

    def bind_tools(self, tools: list) -> ChatOpenAI:
        """动态绑定工具（每次 _call_llm 调用）"""
        return self.primary_model.bind_tools(tools)

    def bind_structured_output(self, schema: type) -> ChatOpenAI:
        return self.primary_model.with_structured_output(schema)

    def strip_thinking_signatures(self, messages: list) -> list:
        """剥离 protected thinking blocks。

        降级到不支持 thinking 的模型时需要。
        参考 Claude Code query.ts: stripSignatureBlocks。
        """
        ...

    @property
    def model_name(self) -> str:
        return self.primary_model.model_name
```

### 4.8 planning/ — 规划系统

#### 4.8.1 planning/schema.py

```python
"""Plan & PlanStep — Pydantic v2 数据模型。

存储位置: LCState.current_plan (dict)
持久化: LangGraph SqliteSaver checkpoint 自动持久化
不需要额外存储层！
"""

class PlanStep(BaseModel):
    step_id: int
    description: str
    status: Literal["pending", "in_progress", "done", "failed", "skipped"] = "pending"
    result: Optional[str] = None     # 执行结果摘要（仅 done 时）
    error: Optional[str] = None      # 失败原因（仅 failed 时）
    tool_hint: Optional[str] = None  # 建议使用的工具

class Plan(BaseModel):
    goal: str
    steps: list[PlanStep]
    status: Literal["active", "completed", "abandoned"] = "active"
    reflection: Optional[str] = None
    created_at: Optional[str] = None

    def current_step(self) -> Optional[PlanStep]: ...
    def mark_current_done(self, result: str) -> None: ...
    def mark_current_failed(self, error: str) -> None: ...
    def mark_current_in_progress(self) -> None: ...
    def retry_current(self) -> None: ...
    def skip_current(self, reason: str) -> None: ...
    def to_display(self) -> str: ...
```

#### 4.8.2 planning/planner.py — plan_create 工具

```python
"""plan_create 工具定义。

工具本身只返回成功 JSON。
真正的 Plan 构建在 router.process_tool_results() 中完成。
原因: 工具函数无法直接修改 LCState（LangChain tool 沙箱限制）。
"""

class PlanCreateInput(BaseModel):
    goal: str = Field(description="计划的最终目标")
    steps: list[str] = Field(
        description="计划步骤列表，每个元素是一个步骤描述，至少包含2个步骤",
        min_length=2,
    )

def create_plan_tool() -> BaseTool:
    @tool("plan_create", args_schema=PlanCreateInput)
    def plan_create(goal: str, steps: list[str]) -> str:
        """创建多步执行计划。

        当任务需要 3 步及以上操作时，调用此工具制定计划。
        系统会自动逐步执行每一步，并在每步完成后进行反思评估。

        简单任务（1-2 步）请直接使用对应工具，无需创建计划。
        """
        return json.dumps(
            {"goal": goal, "steps": steps, "total": len(steps)},
            ensure_ascii=False,
        )
    return plan_create
```

#### 4.8.3 planning/context.py — 计划上下文注入器

```python
"""PlanContextInjector — 将计划上下文注入 LLM 消息。

在 Supervisor._call_llm() 的消息组装阶段调用。
注入策略根据 current_step.status 切换:
  - in_progress → "专注执行第 N 步: xxx" + 已完成步骤摘要
  - pending → "下一步即将开始" + 完整计划展示
  - failed → "步骤失败" + 重试/跳过提示
  - completed → "计划已完成"（让 LLM 自由发挥）
  - abandoned → 不注入
"""

def inject_plan_context(plan_data: dict | None) -> list[SystemMessage]:
    """返回要注入的 SystemMessage 列表。

    调用方在 System 消息区域之后插入这些消息。
    """
    if not plan_data: return []
    plan = Plan(**plan_data)
    ...
```

#### 4.8.4 planning/reflector.py — 结构化反思

```python
"""Reflector — 使用 LLM structured output 评估步骤执行结果。

参考 Claude Code Verification Agent 的对抗性反思理念：
  不是确认正确性，而是试图发现错误。
"""

class ReflectDecision(BaseModel):
    action: Literal["continue", "retry", "skip", "replan"]
    reason: str
    step_summary: str = ""     # 用于后续步骤理解前序进展
    adjustment: str = ""        # 仅 action=replan 时给出调整建议

def create_reflector(llm):
    """返回 (state: LCState) → dict 的 LangGraph 节点函数。

    内部流程:
    1. 注入最近 8 条消息作为执行上下文
    2. 调用 LLM.with_structured_output(ReflectDecision)
    3. 根据 action 更新 Plan 状态
    """
    ...
```

---

## 5. Layer 2: Agent 系统

> **这是 v2 最核心的重构。根本原则：Agent 划分的依据是"隔离需求"，不是"能力类型"。**

### 5.1 设计原则

| 隔离类型 | 何时需要子 Agent | 示例 |
|---------|-----------------|------|
| **Token 空间隔离** | 大量中间操作会污染主对话 | Explore 搜索 → 只返回摘要 |
| **权限隔离** | 子任务需要更严格约束 | Review 只读，即使主Agent bypass |
| **模型降级** | 子任务不需要强模型 | Explore 用便宜模型 |
| **中止控制隔离** | 用户可独立取消子任务 | 取消长时间搜索 |

**如果以上都不需要 → 主 Agent 直接做，不需子图。**

### 5.2 Agent 方案：1 主 + 2 子 + Skill 系统

```
┌──────────────────────────────────────────────────────────────┐
│                   Supervisor（主 Agent）                      │
│  tools: [*] 全部                                              │
│  图: agent → tools → auto_verify → router → 4-way            │
│  内置: auto_verify（所有代码修改自动验证）                      │
│  路由: plan_create / delegate_explore / delegate_review       │
│  默认: 纯 ReAct 处理一切（写代码、读文件、跑命令、查资料）        │
└──────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│  Explore Agent    │  │  Review Agent    │
│  (快速只读搜索)    │  │  (代码审查)       │
│                  │  │                  │
│  tools: 只读      │  │  tools: 只读     │
│  disallowed: 写+   │  │  disallowed: 写+ │
│  递归Agent        │  │  递归Agent       │
│  ★ summarize节点  │  │  ★ report节点    │
│  模型: 可降级     │  │  模型: inherit   │
│  omit_claude_md   │  │  含 CLAUDE.md    │
└──────────────────┘  └──────────────────┘
```

### 5.3 agents/definition.py

```python
"""AgentDefinition — 声明式 Agent 定义。

参考 Claude Code:
- BaseAgentDefinition 统一基类型
- BuiltInAgentDefinition (getSystemPrompt参数化)
- CustomAgentDefinition (从 Markdown frontmatter 加载)
- 优先级覆盖: builtin → user → project → policy

LangCode 简化:
  目前只区分 builtin 和 user（通过 Skill 系统加载自定义Agent）
  聚焦于通过工具约束（tools/disallowedTools）区分 Agent，
  而非提示词差异。
"""

@dataclass
class AgentDefinition:
    agent_type: str          # "explore" | "review"
    description: str
    when_to_use: str = ""

    # ── 提示词 ──
    system_prompt: str = ""
    prompt_file: str = ""    # 或从 resources/prompts/agents/ 加载

    # ── 工具约束 ──
    tools: list[str] = field(default_factory=lambda: ["*"])
    disallowed_tools: list[str] = field(default_factory=list)

    # ── 执行配置 ──
    model: str = "inherit"        # "inherit" | "haiku" | model_name
    permission_mode: str = "inherit"
    max_turns: int = 50
    omit_claude_md: bool = False  # ★ 搜索类 Agent 省 Token

    source: str = "builtin"       # "builtin" | "user" | "project"


# ── 内置 Agent 定义 ──

EXPLORE_AGENT = AgentDefinition(
    agent_type="explore",
    description="快速代码搜索 Agent：搜索文件、阅读代码、分析结构",
    when_to_use="用于需要跨多个文件搜索、阅读和分析的任务",
    tools=["read_file", "search_files", "fetch_api",
           "execute_shell", "memory_search", "memory_list"],
    disallowed_tools=["write_file", "edit_file", "run_python",
                      "delegate_explore", "delegate_review", "plan_create"],
    model="inherit",              # 可配置降级为更便宜的模型
    max_turns=30,
    omit_claude_md=True,          # ★ 搜索不需要 CLAUDE.md
    prompt_file="agents/explore.md",
)

REVIEW_AGENT = AgentDefinition(
    agent_type="review",
    description="代码审查 Agent：审查质量、安全性、发现 bug、提供建议",
    when_to_use="用于代码审查、安全分析、质量评估",
    tools=["read_file", "search_files", "execute_shell", "run_python"],
    disallowed_tools=["write_file", "edit_file",
                      "delegate_explore", "delegate_review", "plan_create"],
    model="inherit",              # 审查需要强推理能力
    max_turns=40,
    omit_claude_md=False,         # ★ 审查需要项目上下文
    prompt_file="agents/review.md",
)
```

### 5.4 agents/supervisor.py — 中枢路由（最终版）

```python
"""Supervisor — 中枢路由编排器。

图结构（6 个节点 + 1 个条件钩子）：

    START
      │
      ▼
   ┌──────┐
   │ agent │ ← _call_llm: 上下文注入 + 动态工具绑定 + LLM 调用
   └──┬───┘
      │ has_tool_calls?
 ┌────┴────┐
 ▼         ▼
┌─────┐   END
│tools│  (无工具调用 → 完成)
└──┬──┘
  │
  ▼
┌─────────────┐
│ auto_verify │ ★ 代码修改后自动验证（所有代码路径）
└──────┬──────┘
       │ verify_errors?
  ┌────┴────┐
  ▼         ▼
 agent    ┌──────┐
(修复)    │router│ ← 提取 plan_create/delegate_* 信号
          └──┬───┘
             │
 ┌───────────┼───────────┬──────────┐
 ▼           ▼           ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐  agent
│mark_   │ │delegate│ │reflect │  (ReAct
│step    │ │_router │ │or      │   继续)
│→ agent │ │→子Agent│ │→agent/ │
└────────┘ │→ END   │ │ END    │
           └────────┘ └────────┘
"""

class Supervisor:
    def __init__(self, llm, checkpointer, tool_registry, agent_defs):
        ...

    def build_graph(self) -> CompiledStateGraph:
        builder = StateGraph(LCState)

        # 6 个节点
        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", self._tool_node)
        builder.add_node("auto_verify", self._auto_verify)     # ★
        builder.add_node("router", process_tool_results)
        builder.add_node("mark_step", self._mark_step)
        builder.add_node("reflector", self._reflect)

        # 边
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", should_use_tools, {
            "tools": "tools", "__end__": END,
        })
        builder.add_edge("tools", "auto_verify")
        builder.add_conditional_edges("auto_verify", self._after_verify, {
            "agent": "agent", "router": "router",
        })
        builder.add_conditional_edges("router", after_tools_routing, {
            "plan_created": "mark_step",
            "delegated": "delegate_router",
            "reflect": "reflector",
            "react": "agent",
            "__end__": END,
        })
        builder.add_edge("mark_step", "agent")
        builder.add_conditional_edges("reflector", self._after_reflect, {
            "agent": "agent", "__end__": END,
        })

        # 子图
        if self.sub_agents:
            builder.add_node("delegate_router", self._delegate_router)
            for name, sub_graph in self.sub_agents.items():
                builder.add_node(f"sub_{name}", sub_graph)
                builder.add_edge("delegate_router", f"sub_{name}")
                builder.add_edge(f"sub_{name}", END)

        return builder.compile(checkpointer=self.checkpointer)

    def _call_llm(self, state: LCState) -> dict:
        """上下文注入 + 工具绑定 + LLM 调用"""
        messages = list(state["messages"])

        # 1. 注入计划上下文
        plan_msgs = inject_plan_context(state.get("current_plan"))

        # 2. 注入记忆上下文
        memory = state.get("memory_context", "")
        if memory:
            plan_msgs.insert(0, SystemMessage(id="memory", content=f"[相关记忆]\n{memory}"))

        # 3. 消息组装：System区域之后插入注入消息
        insert_idx = 0
        for i, m in enumerate(messages):
            if isinstance(m, SystemMessage): insert_idx = i + 1
        for msg in reversed(plan_msgs):
            messages.insert(insert_idx, msg)

        # 4. 上下文裁剪
        messages = self._compact_if_needed(messages)

        # 5. 动态工具绑定（根据 agent_mode 过滤 — 源头拦截！）
        mode = get_app_state().session.agent_mode
        allowed_tools = self.tool_registry.to_langchain_tools(mode)
        bound_llm = self.llm.bind_tools(allowed_tools)
        # ★ LLM 只看到它有权限使用的工具 → 不可能越权调用

        response = bound_llm.invoke(messages)
        return {"messages": [response], "memory_context": ""}

    def _auto_verify(self, state: LCState) -> dict:
        """★ 代码修改后自动验证。

        LangCode 的差异化能力：
        Claude Code 的 Verification Agent 是独立对抗性 Agent；
        LangCode 的 auto_verify 是内联的建设性检查。

        强制执行（不是靠提示词请求 LLM "请检查你的代码"）:
        1. py_compile 语法检查
        2. import 导入检查（动态 import 测试）
        3. ruff linter（可选，如果已安装）
        4. pytest 自动化测试（可选，如果找到相关测试文件）
        """
        if not get_app_state().session.auto_verify:
            return {}
        files = self._extract_modified_python_files(state)
        if not files: return {}

        errors = []
        errors.extend(self._syntax_check(files))
        errors.extend(self._import_check(files))
        errors.extend(self._lint_check(files))
        errors.extend(self._run_tests(files))

        if errors:
            return {
                "messages": [SystemMessage(
                    content="[自动验证失败]\n" + "\n".join(errors) +
                            "\n\n请立即修复以上问题。不要继续下一步。"
                )],
                "verify_errors": errors,
            }
        return {"verify_errors": None}

    def _after_verify(self, state: LCState) -> str:
        return "agent" if state.get("verify_errors") else "router"

    def _mark_step(self, state: LCState) -> dict:
        plan = Plan(**(state.get("current_plan", {})))
        plan.mark_current_in_progress()
        return {"current_plan": plan.model_dump()}

    def _reflect(self, state: LCState) -> dict:
        return create_reflector(self.llm)(state)

    def _after_reflect(self, state: LCState) -> str:
        plan_data = state.get("current_plan")
        if not plan_data: return END
        plan = Plan(**plan_data)
        return "agent" if plan.status == "active" else END

    def _delegate_router(self, state: LCState) -> dict:
        """构建子Agent 输入 — 只有任务描述，不含完整历史"""
        task = state.get("task_description", "")
        return {"messages": [HumanMessage(content=task)]}
```

### 5.5 agents/router.py

```python
"""Router — 工具调用信号提取 + 路由分发。

plan_create 被调用 → 构建 Plan → current_plan
delegate_explore/review 被调用 → route + task_description
"""

def should_use_tools(state: LCState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "__end__"


def process_tool_results(state: LCState) -> dict:
    """识别 LLM tool_calls 中的 plan/delegate 信号"""
    updates = {}
    last_ai = _find_last_ai_with_tool_calls(state["messages"])
    if not last_ai: return updates

    for tc in last_ai.tool_calls:
        if tc["name"] == "plan_create":
            plan = Plan(
                goal=tc["args"]["goal"],
                steps=[PlanStep(step_id=i+1, description=s)
                       for i, s in enumerate(tc["args"]["steps"])]
            )
            updates["current_plan"] = plan.model_dump()

        elif tc["name"].startswith("delegate_"):
            updates["route"] = tc["name"].replace("delegate_", "")
            updates["task_description"] = tc["args"].get("task", "")

    return updates


def after_tools_routing(state: LCState) -> str:
    """四路分发: plan_created → delegated → reflect → react"""
    plan_data = state.get("current_plan")

    # 1. 刚创建计划（所有步骤 pending）
    if plan_data and _is_newly_created(plan_data):
        return "plan_created"

    # 2. 委派
    route = state.get("route", "")
    if route in ("explore", "review"):
        return "delegated"

    # 3. 计划执行中 → 反思
    if plan_data and _is_step_in_progress(plan_data):
        return "reflect"

    # 4. ReAct 循环
    return "react"
```

### 5.6 agents/builtin/explore.py

```python
"""ExploreAgent — 快速只读代码搜索。

对齐 Claude Code Explore Agent:
- 只读工具集 → 安全保证
- 禁止嵌套 Agent → 防止递归爆炸
- 独立消息上下文 → 搜索过程不污染主对话
- ★ summarize 节点 → 中间搜索压缩为结构化摘要
- 可配置降级模型 → 成本优化（搜索用便宜模型）
"""

class ExploreAgent:
    """子图结构:
    START → agent → tools → agent → ... → summarize → summarize_llm → END
    """

    def build_graph(self):
        builder = StateGraph(LCState)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", ToolNode(tools=self.tools))
        builder.add_node("summarize", self._summarize_node)
        builder.add_node("summarize_llm", self._call_llm)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", self._agent_routing, {
            "tools": "tools",
            "summarize": "summarize",
        })
        builder.add_edge("tools", "agent")
        builder.add_edge("summarize", "summarize_llm")
        builder.add_edge("summarize_llm", END)

        return builder.compile(checkpointer=self.checkpointer)

    def _summarize_node(self, state: LCState) -> dict:
        """★ 强制生成结构化摘要。

        注入摘要指令，让后续 LLM 节点输出结构化结果。
        中间搜索细节留在子图上下文——只有摘要进入父图 messages。
        """
        return {"messages": [SystemMessage(content=(
            "[报告生成阶段] 信息收集完毕。\n\n"
            "请基于以上搜索结果生成结构化研究报告：\n"
            "## 研究目标\n[目标描述]\n\n"
            "## 关键发现\n1. [发现1]（含文件路径引用）\n\n"
            "## 代码结构\n[模块/文件 → 作用]\n\n"
            "## 建议\n[可操作建议]\n\n"
            "不要再调用工具。"
        )]}
```

### 5.7 agents/builtin/review.py

```python
"""ReviewAgent — 代码审查。

对齐 Claude Code Verification Agent 的对抗性设计理念：
- 只读工具集 → 审查不能修改代码
- ★ report 节点使用 raw LLM（不绑定工具）→ 防止幻觉 tool_calls
- ★ 对抗性提示词 → "看起来没问题 ≠ 验证过"
- 独立消息上下文 → 只返回结构化报告
"""

class ReviewAgent:
    """子图结构:
    START → agent → tools → agent → ... → report → END
    """

    def build_graph(self):
        builder = StateGraph(LCState)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", ToolNode(tools=self.tools))
        builder.add_node("report", self._report_node)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", self._agent_routing, {
            "tools": "tools",
            "report": "report",
        })
        builder.add_edge("tools", "agent")
        builder.add_edge("report", END)

        return builder.compile(checkpointer=self.checkpointer)

    def _report_node(self, state: LCState) -> dict:
        """使用 raw LLM（不绑定工具）生成审查报告。

        对抗性提示词（参考 Claude Code Verification Agent）:
        - "看起来没问题" → 不是验证，运行它
        - 实现者的测试通过 → 独立验证
        - 忽略格式问题 → 关注逻辑正确性
        """
        messages = list(state["messages"])
        messages.append(SystemMessage(content=(
            "[报告阶段] 审查信息收集完毕。\n\n"
            "请生成结构化审查报告：\n"
            "1. 总体评价\n"
            "2. 严重程度统计（高/中/低）\n"
            "3. 每个问题的位置 + 建议\n"
            "4. 值得肯定的地方\n\n"
            "不要再调用工具。\n\n"
            "=== 反思检查 ===\n"
            "- 你倾向说"看起来正确"吗？确认你实际验证了每个发现。\n"
            "- 有不确定的地方吗？标注为"建议"而非"必须修复"。"
        )))
        response = self.llm.invoke(messages)  # raw LLM，无工具绑定
        return {"messages": [response]}
```

### 5.8 agents/skills/ — Skill 系统

```python
"""Skill 系统 — 可发现、可复用的能力包。

参考 Claude Code Skill 系统:
- Skill = YAML frontmatter + Markdown 正文
- 发现源: .langcode/skills/*.md + 插件 + MCP
- 执行模式: inline（注入提示词）或 fork（子Agent）

内置 Skill:
  - code-review: 审查（用户可自定义标准）
  - refactor: 重构（AST工具优先）
  - write-tests: 测试生成
  - explain-code: 代码解释
  - debug: 调试辅助
"""

@dataclass
class SkillDefinition:
    name: str
    description: str
    prompt: str                      # Markdown 正文（Skill 提示词）
    allowed_tools: list[str]         # Skill 允许的工具
    model: str = "inherit"
    context: str = "fork"            # "fork" (子Agent) | "inline" (注入)

class SkillLoader:
    """从 .langcode/skills/*.md 加载 Skill。

    文件格式（参考 Claude Code）：
    ```markdown
    ---
    name: code-review
    description: "审查代码变更"
    tools: [Read, Grep, Bash]
    model: inherit
    ---

    你是一个代码审查专家...
    ```
    """
    def __init__(self, workspace_dir: str): ...
    def load_all(self) -> list[SkillDefinition]: ...

class SkillRunner:
    """Fork 子Agent 执行 Skill"""
    async def run_skill(self, skill: SkillDefinition,
                        args: str, parent_ctx) -> str: ...
```

---

## 6. Layer 3: tools — 工具系统

### 6.1 tools/base.py — 工具执行结果（v2.1 简化）

> **v2.1 变更**：删除 `Tool[Input, Output]` ABC。LangCode 基于 LangGraph 生态，工具统一使用 LangChain `@tool` 装饰器定义。Tool ABC 是 Claude Code 架构的投影（Claude Code 是纯 TS CLI，无框架），在 LangGraph 中无不可替代职责。
>
> **删除理由**：
> - 0 个 builtin 继承 Tool ABC（全部用 `@tool`）
> - `check_permissions()` 空实现，权限由 `permissions/` 独立承担
> - `is_read_only()` 等分类改为注册时 tags 声明
> - `to_langchain_tool()` 用 `nest_asyncio` 做同步包装——绕了一圈回到 LangChain
>
> **保留 `ToolResult`**：`StreamingToolExecutor` 和 MCP 适配器需要结果封装（`data` + `new_messages` + `context_modifier`）。

```python
class ToolResult:
    """工具执行结果。"""
    data: Any
    new_messages: list = []
    context_modifier: callable | None = None
```

**工具分类策略变更**（v2.1）：

| v2.0 | v2.1 |
|------|------|
| `Tool.is_read_only(args)` 输入驱动 | `registry.register(tool, tags={"read_only"})` 注册时声明 |
| `Tool.is_destructive(args)` 输入驱动 | `BashClassifier` 在执行前分析（已在 L1 实现） |
| `_LangChainToolAdapter` 硬编码分类 | 删除 adapter，tags 随工具注册 |

### 6.2 tools/context.py — ToolUseContext

```python
"""ToolUseContext — 工具执行环境的依赖注入载体。

参考 Claude Code ToolUseContext（40+ 字段）:
- 每个查询轮次创建一个 Context
- 通过参数显式传递（非隐式全局变量）
- 子Agent 创建时继承父 Context 并覆盖 agent_id
- 轮次结束销毁

关键设计（参考 Claude Code）:
- read_file_state: LRU 文件读缓存 → 避免重复 I/O
- can_use_tool: 权限检查回调 → 工具自行调用
- abort_signal: 取消令牌 → 子任务可被父任务取消
"""

@dataclass
class ToolUseContext:
    # ── 会话标识 ──
    session_id: str
    agent_id: str
    workspace_dir: str

    # ── LLM 配置 ──
    model_name: str
    max_output_tokens: int = 8192

    # ── 工具环境 ──
    tools: list = field(default_factory=list)
    can_use_tool: Any = None          # CanUseToolFn 回调
    read_file_cache: dict = field(default_factory=dict)   # LRU
    write_file_state: set = field(default_factory=set)    # 本轮已写入

    # ── 权限 ──
    permission_mode: str = "default"
    allowed_dirs: set = field(default_factory=set)

    # ── MCP ──
    mcp_clients: list = field(default_factory=list)

    # ── 中断控制 ──
    abort_signal: Any = None           # asyncio.Event

    # ── 遥测 ──
    telemetry: dict = field(default_factory=dict)

    def clone_for_subagent(self, agent_id: str) -> "ToolUseContext":
        """子Agent 获得独立的文件缓存 + 写入追踪"""
        ...
```

### 6.3 tools/execution.py — 并发调度器（v2.1 适配）

> **v2.1 变更**：适配 LangChain BaseTool（`ainvoke`/`invoke` 替代 `call`）。`is_concurrency_safe` 由 `ToolRegistry.is_concurrent_safe(name)` 驱动（基于 `TAG_CONCURRENT_SAFE` tag），功能等价于 v2.0 的 `Tool.is_concurrency_safe(args)`。

```python
class StreamingToolExecutor:
    """并发调度器 — 分区策略：

    1. 连续的 concurrent_safe 工具 → 一组 → asyncio.gather 并行
    2. 非 concurrent_safe 工具 → 各自独立串行
    """

    def _partition(self) -> list[dict]:
        """按 TAG_CONCURRENT_SAFE 分组"""
        ...

    async def _execute_concurrent(self, tools) -> AsyncGenerator[ToolResult]:
        """并发执行：asyncio.gather"""
        ...
```

### 6.4 tools/builtin/ — 内置工具

每个工具一个文件，使用 LangChain `@tool` 装饰器定义。权限由 `permissions/` 模块统一管理。

核心工具：
- **FileReadTool**: 文本/图片/PDF/Jupyter 多格式读取，支持 offset/limit 分段
- **FileWriteTool**: 创建文件 + 自动创建父目录
- **FileEditTool**: 唯一性字符串匹配（类似 Claude Code FileEditTool）
- **GlobTool + GrepTool**: ripgrep 集成，支持 regex、上下文行、多行匹配
- **BashTool**: 集成 BashClassifier 安全分析
- **PythonTool**: 沙箱隔离（禁止 os/subprocess/socket/shutil/ctypes 等模块）+ 256MB 内存看门狗
- **WebFetchTool + WebSearchTool**: HTML → Markdown 转换

### 6.5 tools/ast/ — AST 结构化编辑 ★ 差异化功能

```python
"""AST 结构化编辑 — LangCode 相对于 Claude Code 的差异化能力。

Claude Code 没有 AST 工具——所有代码修改通过字符串匹配（FileEditTool）。
LangCode 通过 tree-sitter 实现结构化代码编辑:
- ast_rename: 精确重命名（同作用域标识符，而非全局字符串替换）
- ast_add_param: 为函数添加参数（自动处理 self/cls 位置）
- ast_add_method: 在类中添加方法（自动处理缩进）
- ast_add_import: 添加 import 语句（自动放在现有 import 之后，避免重复）
- ast_info: AST 结构分析（函数、类、import 列表）
- ast_find: 查找指定代码元素（返回精确行号）

扩展点: LanguagePlugin ABC 接口，当前 Python 实现，未来 TS/Go/Rust。
"""
```

---

## 7. Layer 4: engine — 查询引擎

### 7.1 engine/query_engine.py

```python
"""QueryEngine — 会话生命周期管理器。

参考 Claude Code QueryEngine:
- 一个对话一个实例（One QueryEngine per conversation）
- submit_message() → AsyncGenerator[EngineMessage]（AsyncGenerator 管道模式）
- mutableMessages 在多轮 submit_message 之间持久化
- 负责: 上下文组装、Transcript 写入、会话恢复

与 v1 的关键差异:
  v1: main.py 手动 while True: input → graph.stream() → _consume_events()
  v2: QueryEngine.submit_message() 封装完整生命周期
       - 上下文组装（系统提示 + 记忆 + CLAUDE.md）
       - 查询循环（API ↔ 工具执行 状态机）
       - 结果汇总（用量、耗时、权限事件）
"""

class TerminalReason(str, Enum):
    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    TOKEN_BUDGET = "token_budget"
    ABORTED_STREAMING = "aborted_streaming"
    ABORTED_TOOLS = "aborted_tools"
    PROMPT_TOO_LONG = "prompt_too_long"
    MODEL_ERROR = "model_error"

class ContinueReason(str, Enum):
    NEXT_TURN = "next_turn"
    AUTO_COMPACT_RETRY = "auto_compact_retry"
    MAX_OUTPUT_ESCALATE = "max_output_escalate"
    MAX_OUTPUT_RECOVERY = "max_output_recovery"
    TOKEN_BUDGET_CONTINUATION = "token_budget_continuation"


class QueryEngine:
    def __init__(self, config: QueryEngineConfig):
        ...

    async def submit_message(
        self, prompt: str, options=None
    ) -> AsyncGenerator["EngineMessage", None]:
        """一个查询轮次的完整生命周期 — 四阶段:

        1. 上下文组装: 系统提示 + 记忆 + CLAUDE.md
        2. 用户输入处理: 命令 / 普通消息
        3. 查询循环: API ↔ 工具执行 状态机
        4. 结果汇总: 用量、耗时、权限事件
        """
        start_time = time.time()

        # Phase 1: 上下文组装
        system_prompt = await self._build_system_prompt()

        # Phase 2: 用户输入处理
        if prompt.startswith("/"):
            handled, result = await self._handle_command(prompt)
            if handled: yield result; return

        user_msg = HumanMessage(content=prompt)
        self.messages.append(user_msg)
        # Transcript 写入
        self.transcript.append(user_msg)
        yield EngineMessage(type="user_message", data=user_msg)

        # Phase 3: 查询循环
        loop_state = LoopState(
            messages=list(self.messages),
            tool_use_context=self._create_context(),
            turn_count=0,
        )
        try:
            async for event in self._query_loop(loop_state, system_prompt):
                self.messages.append(event.to_message())
                self.transcript.append(event.to_message())
                yield event
        except asyncio.CancelledError:
            yield EngineMessage(type="result", subtype="aborted")
            return

        # Phase 4: 结果汇总
        yield EngineMessage(type="result", subtype="success", data={
            "duration_ms": (time.time() - start_time) * 1000,
            "duration_api_ms": self.total_api_duration,
            "num_turns": loop_state.turn_count,
            "total_usage": self.total_usage,
            "permission_denials": self.permission_denials,
        })
```

### 7.2 engine/query_loop.py — 核心状态机

```python
"""query_loop — 核心查询循环状态机。

参考 Claude Code query.ts queryLoop:
- 无限循环 while True
- 每次迭代: 预处理 → API调用 → 工具执行 → 决策(Continue/Terminal)
- transition 字段记录上一次的 Continue 原因
  （如 collapse_drain_retry 只尝试一次，再次 413 则退回到 reactive compact）
"""

@dataclass
class LoopState:
    messages: list
    tool_use_context: "ToolUseContext"
    turn_count: int = 0
    total_usage: dict = field(default_factory=dict)
    max_output_tokens_override: int | None = None
    max_output_recovery_count: int = 0
    has_attempted_reactive_compact: bool = False
    transition: Optional[ContinueReason] = None


async def query_loop(state: LoopState, system_prompt: str,
                     tools: list, llm) -> AsyncGenerator["EngineMessage", None]:
    """核心状态机:
    while True:
      1. 预处理: compact? collapse drain?
      2. API 流式调用（streaming）
      3. 无工具调用 → 完成决策 (Terminal / Continue)
         - Token 预算检查
         - 413 恢复链: collapse_drain → reactive_compact → error surface
         - max_output 恢复: escalate 8k→64k → recovery message (最多3次)
      4. 有工具调用 → StreamingToolExecutor 执行 → 追加结果 → continue
    """

    MAX_TURNS = get_app_state().session.max_turns
    MAX_RECOVERY = 3
    ESCALATED_MAX_TOKENS = 64_000

    while True:
        state.turn_count += 1
        if state.turn_count > MAX_TURNS:
            yield EngineMessage(type="result", subtype="max_turns")
            return

        # 1. 预处理: 上下文压缩
        compactor = ContextCompactor(llm, llm.model_name)
        token_count = estimate_message_tokens(state.messages)
        if compactor.should_compact(state.messages, token_count).should_compact:
            result = compactor.micro_compact(state.messages)
            state.messages = result if result else state.messages

        # 2. API 流式调用
        bound_llm = llm.bind_tools(tools)
        assistant_msg = None
        async for chunk in bound_llm.astream(state.messages):
            yield EngineMessage(type="stream_chunk", data=chunk)
        # (组装完整的 assistant 消息)

        state.messages.append(assistant_msg)
        state.total_usage["input_tokens"] += assistant_msg.usage.input_tokens or 0
        state.total_usage["output_tokens"] += assistant_msg.usage.output_tokens or 0

        # 3. 无工具调用 → 决策
        if not assistant_msg.tool_calls:
            # Token 预算检查
            tracker = BudgetTracker(...)
            budget_decision = tracker.check(
                state.total_usage["input_tokens"],
                get_app_state().session.token_budget,
            )
            if budget_decision == "stop":
                yield EngineMessage(type="result", subtype="token_budget")
                return
            if budget_decision == "continue":
                state.transition = ContinueReason.TOKEN_BUDGET_CONTINUATION
                continue

            # 正常完成
            yield EngineMessage(type="result", subtype="completed")
            return

        # 4. 执行工具
        executor = StreamingToolExecutor(tool_registry, state.tool_use_context)
        for tc in assistant_msg.tool_calls:
            executor.add_tool(tc)

        try:
            async for tool_result in executor.execute_all():
                yield EngineMessage(type="tool_result", data=tool_result)
                state.messages.append(tool_result.to_message())
            state.transition = ContinueReason.NEXT_TURN
            continue
        except Exception as e:
            # 错误恢复
            recovered = await try_recover(state, e)
            if not recovered:
                yield EngineMessage(type="result", subtype="model_error")
                return
            continue  # 恢复成功 → 继续循环
```

### 7.3 engine/budget.py — Token 预算追踪

```python
"""BudgetTracker — 参考 Claude Code checkTokenBudget。

算法:
  COMPLETION_THRESHOLD = 0.9        # 使用 90% 预算 → 停止
  DIMINISHING_THRESHOLD = 500       # 两次迭代增量 < 500 tokens → 判定为递减
  MIN_CONTINUATIONS = 3             # 收益递减判定需要最少 3 次 continuation 历史

  if agent_id: 子Agent 不参与 Token 预算（由 maxTurns 控制）

决策:
  - 连续 >= 3 次 + 增量均 < 500 → "stop" (收益递减)
  - 使用 >= 90% 预算 → "stop"
  - 子Agent → 跳过检查
  - 否则 → "continue"
"""

COMPLETION_THRESHOLD = 0.9
DIMINISHING_THRESHOLD = 500
MIN_CONTINUATIONS = 3

@dataclass
class BudgetTracker:
    continuation_count: int = 0
    last_delta_tokens: int = 0
    last_global_tokens: int = 0

    def check(self, global_tokens: int, budget: int | None,
              agent_id: str | None = None) -> str:
        """返回 "continue" | "stop" | "below_threshold" """
        if agent_id or not budget or budget <= 0:
            return "below_threshold"

        delta = global_tokens - self.last_global_tokens
        is_diminishing = (
            self.continuation_count >= MIN_CONTINUATIONS
            and delta < DIMINISHING_THRESHOLD
            and self.last_delta_tokens < DIMINISHING_THRESHOLD
        )

        if not is_diminishing and global_tokens < budget * COMPLETION_THRESHOLD:
            self.continuation_count += 1
            self.last_delta_tokens = delta
            self.last_global_tokens = global_tokens
            return "continue"

        return "stop"
```

### 7.4 engine/recovery.py — 错误恢复链

```python
"""错误恢复链 — 参考 Claude Code query.ts 错误处理。

恢复优先级（从轻到重）:
  1. max_output_tokens 截断:
     a. escalate: 8k → 64k（如果 capability 允许）
     b. recovery message: 注入 "Output token limit hit. Resume directly."
        （最多 3 次，措辞精心设计——"no apology, no recap"）
  2. 413 prompt_too_long:
     a. collapse drain: 清除暂存的 collapse → 释放空间
     b. reactive compact: 执行全量上下文压缩
        （collapse_drain 只尝试一次，再次 413 则退回到 compact）
     c. error surface: 压缩后仍然超限 → 向用户展示错误
  3. 模型不可用:
     a. fallback model: 切换到备用模型
     b. thinking 签名剥离（如果 fallback 不支持 thinking）

被扣留（withheld）的消息：
  可恢复的错误消息不立即 yield，只有恢复手段用尽后才表面化。
  这防止 SDK 消费者在恢复成功时收到虚假的错误信号。
"""

MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3
ESCALATED_MAX_TOKENS = 64_000


async def try_recover(state: LoopState, error: Exception,
                       llm, compactor) -> bool:
    """尝试从错误中恢复。返回 True 表示恢复成功可重试。"""

    # ── max_output_tokens 截断 ──
    if _is_max_output_tokens_error(error):
        # a. 升级到 64k
        if state.max_output_tokens_override is None:
            state.max_output_tokens_override = ESCALATED_MAX_TOKENS
            state.transition = ContinueReason.MAX_OUTPUT_ESCALATE
            return True

        # b. 注入恢复消息（最多3次）
        if state.max_output_recovery_count < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT:
            recovery_msg = HumanMessage(
                content="Output token limit hit. Resume directly — "
                        "no apology, no recap. "
                        "Pick up mid-thought if that is where the cut happened. "
                        "Break remaining work into smaller pieces.",
                is_meta=True,
            )
            state.messages.append(recovery_msg)
            state.max_output_recovery_count += 1
            state.transition = ContinueReason.MAX_OUTPUT_RECOVERY
            return True

        return False  # 恢复次数耗尽

    # ── 413 prompt_too_long ──
    if _is_prompt_too_long_error(error):
        # a. collapse drain（只尝试一次）
        if state.transition != ContinueReason.AUTO_COMPACT_RETRY:
            state.transition = ContinueReason.AUTO_COMPACT_RETRY
            return True

        # b. reactive compact
        if not state.has_attempted_reactive_compact:
            result = compactor.auto_compact(state.messages)
            if result.was_compacted:
                state.messages = result.output
                state.has_attempted_reactive_compact = True
                state.transition = ContinueReason.AUTO_COMPACT_RETRY
                return True

        return False  # compact 后仍然超限

    # ── 模型不可用 → fallback ──
    if _is_model_unavailable_error(error) and llm.fallback_model:
        llm.primary_model, llm.fallback_model = llm.fallback_model, llm.primary_model
        # 剥离 thinking 签名（fallback 可能不支持）
        state.messages = llm.strip_thinking_signatures(state.messages)
        return True

    return False
```

### 7.5 engine/context.py — 系统提示组装

```python
"""系统提示组装流水线。

参考 Claude Code fetchSystemPromptParts:
  多源拼接: defaultSystemPrompt + userContext + systemContext + CLAUDE.md + memory + plan

层次结构:
  1. base.md             — 基础角色 + 安全准则 + 工具使用规则
  2. platform_xxx.md     — 操作系统/Shell类型
  3. CLAUDE.md           — 项目说明
  4. memory_context      — 记忆检索结果
  5. plan_context        — 当前计划步骤
  6. custom_system_prompt — 用户自定义追加
"""

async def build_system_prompt(
    workspace_dir: str,
    platform: str,
    custom_prompt: str = "",
) -> str:
    """组装最终的系统提示词。

    多源按顺序拼接，使用明确的 ID 标记各段来源，
    方便后续的上下文压缩识别可压缩的部分。
    """
    parts = []

    # 1. 基础提示词（角色 + 安全规则 + 工具使用约定）
    parts.append(load_prompt_file("base.md"))

    # 2. 平台特定信息（OS、Shell、Python版本）
    platform_file = f"platform_{platform}.md"
    parts.append(load_prompt_file(platform_file))

    # 3. CLAUDE.md（项目说明 — 精确注入，非全量）
    claude_md = find_claude_md(workspace_dir)
    if claude_md:
        parts.append(f"<!-- CLAUDE.md -->\n{claude_md}")

    # 4. 自定义追加
    if custom_prompt:
        parts.append(f"<!-- custom -->\n{custom_prompt}")

    return "\n\n".join(parts)
```

---

## 8. Layer 5: cli — CLI/UI 层

### 8.1 main.py — 入口（<80 行）

```python
"""LangCode Agent 入口。

用法:
  python main.py            # 命令行 REPL
  python main.py --tui      # Textual TUI
"""

import sys
import asyncio
from pathlib import Path


def create_engine(workspace_dir: str | None = None) -> QueryEngine:
    """组装所有子系统，创建 QueryEngine。

    组装顺序（严格按依赖关系）:
    1. Config（分层配置）
    2. AppState（全局 Store）
    3. LLMClient + PermissionEngine + MemoryStore + ToolRegistry
    4. AgentDefinition + Supervisor（含子图）
    5. QueryEngine
    """
    workspace = workspace_dir or str(Path.cwd())

    # Layer 1: 配置
    config = Config.load(workspace)
    llm_client = LLMClient(config)

    # Layer 1: 状态
    init_app_state(config)

    # Layer 1: 权限
    rule_engine = RuleEngine()
    rule_engine.load_rules(workspace)

    # Layer 3: 工具注册
    registry = ToolRegistry()
    register_all_builtin_tools(registry)
    register_ast_tools(registry)
    register_mcp_tools(registry)

    # Layer 1: 记忆
    memory_store = SQLiteMemoryStore()
    memory_manager = MemoryManager(store=memory_store, llm=llm_client.primary_model)
    register_memory_tools(registry, memory_store, memory_manager)

    # Layer 1: 规划工具
    registry.register(create_plan_tool())

    # Layer 2: 子Agent（仅 Explore 和 Review）
    explore_agent = ExploreAgent(llm_client, None, registry.list_all(), EXPLORE_AGENT)
    review_agent = ReviewAgent(llm_client, None, registry.list_all(), REVIEW_AGENT)

    # Layer 2: Supervisor（含子图）
    supervisor = Supervisor(llm_client, None, registry, {
        "explore": EXPLORE_AGENT,
        "review": REVIEW_AGENT,
    })
    supervisor.sub_agents = {
        "explore": explore_agent.build_graph(),
        "review": review_agent.build_graph(),
    }

    # Layer 4: QueryEngine
    return QueryEngine(QueryEngineConfig(
        workspace_dir=workspace,
        llm_client=llm_client,
        tool_registry=registry,
        permission_engine=rule_engine,
        agent_registry={"explore": EXPLORE_AGENT, "review": REVIEW_AGENT},
        session_id=_generate_session_id(),
        config=config,
    ))


def main():
    engine = create_engine()

    if "--tui" in sys.argv:
        from LangCode.cli.tui.app import run_tui
        run_tui(engine)
    else:
        from LangCode.cli.repl import run_repl
        asyncio.run(run_repl(engine))


if __name__ == "__main__":
    main()
```

---

## 9. Plan 生命周期全流程

```
用户输入复杂任务
    │
    ▼
Supervisor._call_llm()
    │  LLM 判断: 任务需要 3+ 步 → 调用 plan_create(goal="...", steps=["...", ...])
    ▼
tools 节点执行 plan_create
    │  返回: {"goal": "...", "steps": [...], "total": N}
    ▼
router.process_tool_results()
    │  识别 plan_create → 构建 Plan → plan.model_dump() → 写入 LCState.current_plan
    │  所有步骤 status = "pending"
    ▼
router.after_tools_routing() → "plan_created"
    │  (判定: _is_newly_created → 所有步骤都是 pending)
    ▼
mark_step 节点
    │  plan.mark_current_in_progress() → step1.status = "in_progress"
    │  plan.model_dump() → {"current_plan": ...}
    ▼
agent 节点
    │  inject_plan_context() 根据 current_step 状态注入:
    │  → step1 in_progress: SystemMessage("🔧 专注执行第1步: xxx")
    │  → 已完成步骤摘要（如果有）
    │  LLM 执行步骤1 → 调用工具 → 得到结果
    ▼
tools 节点（执行 LLM 请求的工具）
    │
    ▼
auto_verify 节点 ★
    │  如果修改了 Python 文件 →
    │    语法检查 + 导入检查 + lint + 测试
    │  验证失败 → 回到 agent 修复
    │  验证通过 → 继续
    ▼
router.process_tool_results() → 无 plan/delegate 信号 → 无更新
    ▼
router.after_tools_routing() → "reflect"
    │  (判定: 有 active plan + 有 in_progress 步骤)
    ▼
reflector 节点
    │  LLM structured output → ReflectDecision(action="continue", step_summary="...")
    │  plan.mark_current_done(step_summary) → step1.status = "done"
    │  如果所有步骤 done → plan.status = "completed"
    │  plan.model_dump() → {"current_plan": ...}
    ▼
_after_reflect() → "agent" (还有 pending 步骤)
    │
    ▼
agent → tools → auto_verify → router → reflector → agent → ...
    │  ...循环直到所有步骤完成...
    │
    ▼
reflector → action="continue" → mark_current_done → status="completed"
    ▼
_after_reflect() → END

── 持久化 ──
Plan 始终存储在 LCState.current_plan (dict)
LangGraph SqliteSaver checkpoint 自动持久化整个 LCState
每步状态变更后写回 {"current_plan": plan.model_dump()}
进程崩溃 → 从 checkpoint 恢复 → Plan 状态完整保留
```

---

## 10. Agent Delegation 全流程

```
用户: "帮我审查 src/tools/ 的代码安全性"
    │
    ▼
Supervisor._call_llm()
    │  LLM: 审查任务 → 调用 delegate_review(task="审查 src/tools/ ...")
    │  ★ 为什么 LLM 会选择 delegate_review 而非自己审查？
    │    因为 system prompt 中描述了: "代码审查任务 → 委派给 review Agent"
    │    + delegate_review 工具的 description: "将代码审查任务委派给审查专家Agent"
    │    → LLM 通过 tool calling 做出路由决策（与 Claude Code AgentTool 同理念）
    ▼
tools 节点执行 delegate_review
    │  返回: {"agent": "review", "task": "..."}
    ▼
router.process_tool_results()
    │  识别 delegate_review → 写入:
    │    LCState.route = "review"          （消费后清理? 不，留在 state 供调试）
    │    LCState.task_description = "审查 src/tools/ ..."
    ▼
router.after_tools_routing() → "delegated"
    │  (判定: route == "review" → delegated)
    ▼
delegate_router 节点
    │  构建子Agent 输入消息:
    │    HumanMessage(content=task_description)
    │  ★ 只传入任务描述——不含主对话完整历史（隔离 Token 空间）
    │  ★ 子图共享 LCState，初始 messages 从这条 HumanMessage 开始
    ▼
sub_review 子图 (ReviewAgent.build_graph())
    │  START → agent → tools → agent → ... → report → END
    │
    │  子图内部:
    │  - 使用独立的 ToolNode(tools=review_only_tools)
    │    只暴露 read_file, search_files, execute_shell, run_python
    │  - 消息历史: [HumanMessage(task), AIMessage(...), ToolMessage(...), ...]
    │  - 中间工具调用结果在子图内，不污染主对话
    │  - _agent_routing: 无 tool_calls + 已有工具调用 → report
    │                   无 tool_calls + 还没有工具调用 → tools（至少走一轮）
    │                  有 tool_calls → tools
    │  - report 节点: raw LLM（不绑定工具）→ 生成结构化报告
    │    → 防止 LLM 在报告阶段幻觉调用工具
    │
    ▼
sub_review → END（子图编译的 END）
    │  子图执行完毕。子图内的所有 messages 由 LangGraph 追加到父图 LCState.messages。
    │  ★ 但只有子图的消息进入父图——review 子图没有 summarize 节点
    │    （因为 review 通常没有大量中间结果，报告本身就足够简洁）
    │  ★ 如果 report LLM 输出过长 → 父图的 MicroCompact 会裁剪
    ▼
图结构: sub_review → END（到达父图的 END）
    │  整个查询轮次结束
    │  用户看到: 结构化审查报告

── 与 v1 的关键差异 ──
v1 (当前):
  - delegate_router 注入完整任务描述后，子图所有中间消息追加到父图 messages
  - 子图搜索的 raw 结果污染主对话 → Token 膨胀

v2 (优化):
  - Explore: summarize 节点压缩中间搜索为结构化摘要
  - Review: report 节点使用 raw LLM 生成报告
  - 只有最终的结构化输出（摘要/报告）占用父图 Token 空间

── 委派触发机制 ──
为什么用 tool_calling 而非文本解析?
  v1: 正则解析 [route: xxx] 标签 → 不可靠、非标准
  v2: delegate_explore/review 工具 → LLM 原生 tool calling 能力
       tool calling 是 LLM 训练时就学会的结构化输出方式
       工具名明确标注委派目标，参数 task 提供完整任务描述
       与 Claude Code AgentTool 同理念
```

---

## 11. Agent 划分原则与设计理由

### 11.1 核心原则

**Agent 划分的依据是"隔离需求"，不是"能力类型"。**

```
需要隔离 Token 空间 → 子 Agent（以子图方式）
需要隔离权限     → 子 Agent
需要独立中止控制 → 子 Agent
需要降级模型     → 子 Agent

以上都不需要     → 主 Agent 直接做
```

### 11.2 为什么没有 Code Agent？

Claude Code 没有 Code Agent。GeneralPurpose Agent（`tools: ["*"]`）直接写代码。

Code Agent 作为独立子图**不满足任何一个隔离需求**：
- 和主 Agent 用同样的工具、同样的权限、同样的模型
- 不需要 Token 隔离（写代码不像搜索那样产生大量中间结果）
- 没有独立中止控制需求

但 **verify 闭环本身有价值**。解决方案：
- 将 verify 提升为**主图的 `auto_verify` 节点**，所有代码修改路径自动验证
- 这是"硬保证"——不是靠提示词请求 LLM "请检查"，而是强制执行

### 11.3 为什么 Explore 是子图？

| 需求 | 满足? | 分析 |
|------|------|------|
| Token 隔离 | ✅ | 搜索大量文件结果不应污染主对话。summarize 节点压缩为摘要 |
| 权限隔离 | ✅ | `disallowedTools` 硬保证只读 |
| 模型降级 | ✅ | 可配置为更便宜的模型（`model: "haiku"`） |
| 中止控制 | ✅ | 用户可取消长时间搜索而不影响主对话 |

### 11.4 为什么 Review 是子图？

| 需求 | 满足? | 分析 |
|------|------|------|
| Token 隔离 | ✅ | 审查过程文件读取不污染主对话。report 节点只输出报告 |
| 权限隔离 | ✅ | `disallowedTools` 硬保证只读 |
| 模型降级 | ❌ | 审查需要强推理能力 → `model: "inherit"` |
| 中止控制 | ✅ | 用户可取消审查 |

**Review 也可作为 Skill（更灵活）。** 用户可在 `.langcode/skills/code-review.md` 定义审查标准。Skill 通过 fork 子Agent 执行，效果等价。

---

## 12. 上下文压缩全流程

```
每次 _call_llm 调用时触发压缩检查:

messages → estimate_message_tokens() → token_count
    │
    ▼
ContextCompactor.should_compact(messages, token_count)
    │  threshold = effectiveWindow - AUTOCOMPACT_BUFFER (13,000)
    │
    ├─ token_count < threshold → 无需压缩 → 继续
    │
    └─ token_count > threshold → 触发压缩:
         │
         ▼
       MicroCompact（最轻量）
         │  裁剪 COMPACTABLE_TOOLS 中 > 2000 字符的输出
         │  替换为 "[Old tool result content cleared]"
         │
         ├─ 仍然超限? → AutoCompact
         │    检查断路器: consecutive_failures >= 3 → 跳过
         │    分离 System + 最近10条 + 其余
         │    LLM 将"其余"压缩为 3-5 句摘要
         │    组装: System + 摘要(SystemMessage) + 最近消息
         │    成功 → 重置 consecutive_failures = 0
         │    失败 → consecutive_failures += 1
         │
         └─ 仍然超限? → SnipCompact
              基于文件当前状态替换历史内容
              "File X has current content: ..."

── 压缩边界标记 ──
压缩后在消息中插入 SystemMessage(id="compact_boundary"):
  "[上下文压缩] 早期对话已压缩为摘要。"
让 LLM 知道对话历史被截断，避免引用已不存在的内容。

── 断路器 ──
参考 Claude Code 真实事故数据:
  "BQ 2026-03-10: 1,279 sessions had 50+ consecutive failures (up to 3,272)"
  → 连续失败 3 次后停止尝试，防止浪费 API 调用。
```

---

## 13. 错误恢复链

```
API 调用/工具执行发生错误
    │
    ├─ max_output_tokens 截断 (stop_reason="max_output_tokens")
    │   ├─ 1st: escalate 8k → 64k maxOutputTokens，重试
    │   ├─ 2nd-4th: 注入 recovery message（最多3次）
    │   │   "Output token limit hit. Resume directly — no apology, no recap."
    │   └─ 超过3次 → 放弃，返回 model_error
    │
    ├─ 413 prompt_too_long
    │   ├─ 1st: collapse_drain（清除暂存 collapse）→ 重试
    │   │   （transition != collapse_drain_retry 时才执行——只尝试一次）
    │   ├─ 2nd: reactive_compact（执行全量上下文压缩）→ 重试
    │   └─ 压缩后仍然超限 → 错误表面化，向用户展示
    │       ★ 被扣留（withheld）的消息：可恢复的错误在恢复过程中不 yield
    │         只有恢复手段用尽后才向调用方表面化
    │
    └─ 模型不可用 (ModelUnavailableError / rate_limit)
        ├─ 切换到 fallback 模型（如果已配置）
        ├─ 剥离 thinking 签名（fallback 可能不支持）
        │   "Thinking signatures are model-bound: replaying a protected-thinking
        │    block to an unprotected fallback 400s."
        └─ 没有 fallback → 错误表面化
```

---

## 14. 工程品质保障

### 14.1 测试策略（参考 Claude Code 测试金字塔）

| 层次 | 内容 | 数量 | 成本 |
|------|------|------|------|
| **单元测试** | 纯函数逻辑：Token 估算、消息裁剪、Plan 状态转换、权限规则匹配、BudgetTracker | 最多 | 低 |
| **组件测试** | 工具执行：FileEditTool 匹配、BashClassifier 分类、StreamingToolExecutor 调度 | 中 | 中 |
| **集成测试** | 图流程：plan_create→mark_step→reflect→complete 全路径、delegate→子图→返回 | 中 | 中 |
| **E2E 测试** | CLI 入口：真实 API 调用、完整多轮对话、中断恢复 | 最少 | 高 |

**关键测试夹具（Harness）**:

```python
# 消息工厂函数 — 参考 Claude Code createTestUserMessage
def make_user_msg(content: str) -> HumanMessage: ...
def make_ai_msg(content: str, tool_calls=None) -> AIMessage: ...
def make_tool_msg(name: str, content: str, call_id: str) -> ToolMessage: ...

# 状态工厂
def make_state(messages=None, agent_mode="build", current_plan=None) -> LCState: ...

# Mock LLM（可编程响应）
class MockLLM:
    """预设多轮响应序列，用于图流程测试。避免真实 API 调用。"""
    def set_responses(self, responses: list[dict]): ...
```

### 14.2 可观测性（参考 Claude Code 数据驱动文化）

```python
# analytics.py — 关键路径计时 + 事件收集
class AnalyticsTracker:
    def record_startup_phase(self, phase: str, duration_ms: int): ...
    def record_api_call(self, model: str, input_tokens: int, output_tokens: int,
                        duration_ms: int, cache_hit: bool): ...
    def record_tool_call(self, tool_name: str, success: bool, duration_ms: int): ...
    def record_compact(self, strategy: str, tokens_before: int, tokens_after: int): ...
    def record_error(self, error_type: str, recovered: bool): ...
    def get_snapshot(self) -> AnalyticsSnapshot: ...

# 关键指标（参考 Claude Code 量化精度）:
# - 启动时间（import_time, init_time, total_time）
# - API 调用次数/耗时/token 消耗
# - 压缩触发频率 + 成功率
# - 工具调用成功率 + 耗时分布
# - 断路器触发次数
```

### 14.3 循环依赖预防

```python
"""打破循环依赖 — 参考 Claude Code types/ 目录的纯类型文件设计。

策略:
1. shared/types.py — 仅 TypedDict + Protocol 定义，零运行时依赖
2. shared/models.py — 仅 Pydantic 模型，无 import 业务逻辑
3. shared/errors.py — 仅异常类，无 import 业务逻辑
4. 所有业务模块单向依赖 shared/
5. Layer 1 模块之间互不 import
6. 如需跨模块通信 → 通过 Store 订阅或依赖注入
"""
```

---

## 15. 实施路线图

```
Phase 1 (2-3天): 稳定基础 — 零风险
  □ 创建 shared/errors.py
  □ 创建 state/store.py + state/app_state.py
  □ 创建 services/config.py + services/llm.py（从 shared 迁移）
  □ 精简 shared/types.py — 17 → 8 字段
  □ 迁移 shared/schemas.py → shared/models.py
  □ 验证: python main.py 仍可运行（向后兼容）

Phase 2 (3-4天): 工具系统 + 权限 — 中风险
  □ 创建 tools/base.py (Tool ABC) + tools/context.py (ToolUseContext)
  □ 创建 tools/registry.py
  □ 迁移 7 内置工具到 tools/builtin/（每工具一个文件，自包含）
  □ 迁移 AST 到 tools/ast/（抽象 LanguagePlugin）
  □ 创建 tools/execution.py (StreamingToolExecutor)
  □ 创建 permissions/（五层防线）
  □ 编写工具层单元测试（BudgetTracker, BashClassifier, ToolRegistry）
  □ 验证: plan 模式不可写；工具在正确模式下过滤

Phase 3 (4-5天): 查询引擎 — 高风险
  □ 创建 engine/query_engine.py + query_loop.py
  □ 创建 engine/budget.py + engine/recovery.py
  □ 创建 state/session.py (Transcript JSONL) + state/compact.py (三层压缩)
  □ 重构 main.py 使用 QueryEngine
  □ 编写查询引擎集成测试（MockLLM 驱动的图测试）
  □ 验证: REPL 和 TUI 两种模式均可运行

Phase 4 (3-4天): Agent 系统重组 — 中风险
  □ 创建 agents/definition.py + agents/router.py
  □ 重建 Supervisor: 6 节点图 + auto_verify 节点
  □ 迁移 Explore + Review 为精简子图（summarize/report 节点）
  □ 去掉 Code Agent（verify 已提升到主图）
  □ 创建 agents/skills/（SkillLoader + SkillRunner）
  □ 编写 Agent 层集成测试（plan → execute → reflect 全流程）
  □ 验证: delegate_explore / delegate_review 子Agent 正常

Phase 5 (1-2天): 收尾
  □ 清理废弃文件: shared/delegate_tools.py, shared/plan_tools.py,
                  planning/tools.py, agents/delegate_tools.py,
                  shared/plan_tools.py 等重复文件
  □ 更新 CLAUDE.md + ARCHITECTURE.md
  □ 编写 E2E 测试（真实 API 调用的对话场景）
  □ 性能基准测试（启动时间、API 延迟、工具执行耗时）

═════════════════════════════════════
  总计: 13-18 天
  每个 Phase 独立可合并，不形成长期分支
  每个 Phase 结束后 python main.py 可运行
═════════════════════════════════════
```

---

## 16. 与 Claude Code 的完整对比

| 维度 | Claude Code (v2.1.x) | LangCode v1 (现状) | LangCode v2 (目标) | 对齐? |
|------|---------------------|-------------------|-------------------|------|
| **运行时** | Bun + TypeScript | Python + LangGraph | Python + LangGraph | N/A |
| **架构分层** | 5 层 (CLI→QE→Tools→Agent→Protocol) | 无分层（shared 17文件混放） | 5 层（Layer 0-5） | ✅ |
| **查询引擎** | QueryEngine (submitMessage → AsyncGenerator) | main.py 手动 graph.stream() | QueryEngine (submit_message → AsyncGenerator) | ✅ |
| **核心循环** | queryLoop 状态机 (Continue/Terminal) | 无状态机 | query_loop 状态机 | ✅ |
| **工具接口** | Tool<I,O,P> 泛型接口 (30+ 方法) | @tool 装饰器（无统一接口） | LangChain `@tool` + ToolResult（v2.1: 删除 Tool ABC） | ⚠️ 简化 |
| **工具注册** | tools.ts 动态组装 + Feature Flag | main.py 手动组装列表 | ToolRegistry + ToolEntry tags（v2.1） | ✅ |
| **并发调度** | StreamingToolExecutor (queued→executing→completed→yielded) | 串行执行 | StreamingToolExecutor（v2.1: TAG_CONCURRENT_SAFE 驱动，功能等价） | ✅ |
| **权限模式** | 6 层 (plan/acceptEdits/default/dontAsk/bypass/auto) | 2 层 (plan/build) | 5 层 (plan/acceptEdits/default/dontAsk/bypass) | ✅ |
| **权限规则** | Allow/Deny/Ask + 多源合并（policy>project>user） | 无规则引擎 | RuleEngine + 三层优先级 | ✅ |
| **Bash 安全** | 引号状态机 + 11种命令替换检测 + Zsh检测 | 无 | BashClassifier（同理念） | ✅ |
| **状态管理** | Store<T> (34行) + AppState | 无（LCState 承担一切） | Store<T> (34行) + AppState | ✅ |
| **会话持久化** | Transcript JSONL + parent_uuid链 | SessionStore 独立（元数据） + checkpoint（消息） | Transcript JSONL + checkpoint互补 | ✅ |
| **上下文压缩** | MicroCompact → AutoCompact → SnipCompact | sliding window trim + 一次性 LLM 摘要 | 三层压缩 + 断路器 | ✅ |
| **Token 预算** | BudgetTracker + 收益递减检测 (90%/500tokens/3次) | 无 | BudgetTracker（同算法） | ✅ |
| **错误恢复** | 413→collapse→compact / max_output→escalate→recovery(×3) / fallback | 无 | 恢复链（同策略） | ✅ |
| **主 Agent** | GeneralPurpose (tools: `*`) | Supervisor (tools `*` + plan + delegate) | Supervisor (tools: `*`) + auto_verify | ✅ |
| **搜索 Agent** | Explore (只读, haiku, 无 CLAUDE.md, 3400万次/周) | ResearchAgent (全量消息追加) | ExploreAgent (只读, 可降级, omit_claude_md, summarize) | ✅ |
| **审查 Agent** | Verification (对抗性, background, 红色标识) | ReviewAgent (全量消息追加) | ReviewAgent (report raw LLM, 对抗性提示) | ✅ |
| **代码编写** | GeneralPurpose 直接写 | CodeAgent 独立子图 | Supervisor 直接写 + auto_verify | ✅ 增强 |
| **规划** | Plan Agent (独立子Agent, 只读) | create_plan_node (通过 tool calling 触发) | plan_create 工具 + 图内流程 | ⚠️ 简化 |
| **Skill 系统** | YAML frontmatter + Fork Agent + inline两种模式 | 无 | YAML frontmatter + Fork Agent | ✅ |
| **Agent 定义** | Markdown frontmatter + builtin + plugin三种源 | 无（硬编码） | AgentDefinition + Skill 系统 | ✅ |
| **Fork 机制** | buildForkedMessages (共享 prefix + 独立 directive) | 子图共享 LCState | 子图 + delegate_router 独立入口 | ✅ |
| **流式处理** | AsyncGenerator 全链路管道 | graph.stream() 双模式(updates+messages) | AsyncGenerator 全链路管道 | ✅ |
| **TUI** | React + Ink + Yoga Flexbox | Textual (Python) | Textual + AgentBridge | N/A |
| **Prompt Cache** | Fork 共享 byte-exact prefix | N/A (API层未优化) | N/A (API约束) | — |
| **Feature Flag** | bun:bundle 编译时 DCE | 无 | 无（Python运行时替代） | — |
| **遥测** | OpenTelemetry + BigQuery | logging | AnalyticsTracker | ✅ 简化 |
| **AST 编辑** | 无 | tree-sitter Python 重命名/加参数/加方法/加import | 同 v1 + LanguagePlugin 扩展点 | ❌ 独有 |
| **auto_verify** | 无（靠 Verification Agent 独立验证） | CodeAgent write→verify→fix | 主图内联 auto_verify 节点 | ❌ 独有 |
| **代码量** | ~1800 文件, ~49万行 TS/TSX | ~25 文件, ~4000行 Python | ~55 文件, ~6000行 Python | N/A |

---

## 附录 A: v2.1 变更日志

> 审查日期: 2026-06-20
> 变更驱动: 架构审查发现 3 类问题 + 1 项接口简化

### A.1 删除 Tool[Input,Output] ABC

**文件**: `tools/base.py`, `tools/__init__.py`, `tools/mcp/adapter.py`, `tools/mcp/__init__.py`

**变更**:
- `Tool[Input,Output]` ABC 类删除（含 `call()`, `check_permissions()`, `is_read_only()`, `to_langchain_tool()` 等 30+ 方法）
- `ToolResult` 保留，去掉泛型参数
- `MCPToolAdapter` 不再继承 `Tool`，改为返回 `BaseTool` 的工厂函数 `_build_mcp_tool()`
- `tools/__init__.py` 移除 `Tool` re-export

**理由**: LangCode 基于 LangGraph，工具统一用 LangChain `@tool` 定义。Tool ABC 是 Claude Code（纯 TS CLI，无框架）架构的投影，在 LangGraph 生态中无不可替代职责。权限由 `permissions/` 独立承担，schema 由 Pydantic 承担，执行由 LangChain 承担——三层职责均已有人负责。

### A.2 简化 ToolRegistry，删除 _LangChainToolAdapter

**文件**: `tools/registry.py`

**变更**:
- 新增 `ToolEntry(tool: BaseTool, tags: frozenset[str])` 数据类
- `register(tool: BaseTool, *, tags)` 替代旧的 `register(tool: Tool)` + 自动适配
- 删除 `_LangChainToolAdapter` 类（不再需要双接口桥接）
- 工具分类从 `is_read_only()` 方法调用改为注册时 `tags` 声明

**tags 定义**:
| tag | 含义 |
|-----|------|
| `read_only` | 不修改文件系统 |
| `destructive` | 不可逆操作 |
| `plan_allowed` | plan 模式下允许（非只读但安全） |

### A.3 控制流反转：registry 不再知道 L1 模块

**文件**: `tools/registry.py`, `main.py`

**变更**:
- 删除 `register_plan_tools()` 和 `register_memory_tools()`（从 registry 移到 main.py）
- `main.py` 直接调用 `create_todo_tools()` / `create_memory_tools()` 后注入 `registry.register_many()`
- registry 只负责注册，不知道 planning/memory 的存在

**之前**:
```python
# tools/registry.py（L3 主动 import L1）
def register_plan_tools(registry):
    from LangCode.planning.todo_tools import create_todo_tools
```

**之后**:
```python
# main.py（composition root 统一编排）
from LangCode.planning.todo_tools import create_todo_tools
registry.register_many(create_todo_tools(), tags=frozenset({TAG_PLAN_ALLOWED}))
```

### A.4 L2→L3 向上依赖消除

**文件**: `agents/prompts.py`, `main.py`

**变更**:
- `get_platform_prompt()` 新增 `bash_path: str | None` 参数
- `_render_windows_prompt()` 不再 import `tools.builtin.shell.get_shell`
- `main.py` 中调用 `get_platform_prompt(bash_path=get_shell())`，跨层协调由 composition root 承担

**之前**（L2→L3 向上违规）:
```python
# agents/prompts.py
from LangCode.tools.builtin.shell import get_shell  # L2 import L3 ❌
```

**之后**:
```python
# main.py
from LangCode.tools.builtin.shell import get_shell  # composition root，合法
platform_prompt = get_platform_prompt(bash_path=get_shell())
```

### A.5 v2.1 依赖图验证结果

```
Upward violations:     NONE — strict monotonic downward ✅
L3 → L1:               shell.py → permissions.classifier（合法向下）
L2 → L3:               NONE ✅
L1 intra-module:       完全隔离 ✅
main.py composition:   正确连接 L0-L5 ✅
```

### A.6 并发调度器恢复

初始 v2.1 将 `StreamingToolExecutor` 简化为串行执行（理由：LangChain BaseTool 无 `is_concurrency_safe` 接口）。经审查确认这是错误简化——生产级 Agent 必须支持并发工具执行。

修复方案：`is_concurrency_safe` 改为 `TAG_CONCURRENT_SAFE` tag 驱动，通过 `ToolRegistry.is_concurrent_safe(name)` 查询，功能等价于 v2.0 的 `Tool.is_concurrency_safe(args)`。分区逻辑（`_partition`）和并发执行（`asyncio.gather`）完整保留。
