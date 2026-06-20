# LangCode v2.1 — 变更方案

> 基于 v2.0 架构审查，修复 3 类架构问题 + 1 项接口简化，版本迭代至 v2.1。
>
> 审查日期: 2026-06-20

---

## 变更总览

| # | 问题 | 严重性 | 修复方式 |
|---|------|--------|---------|
| 1 | `Tool[Input,Output]` ABC 在 LangGraph 生态中冗余 | 架构 | 删除 ABC，统一使用 LangChain `@tool` |
| 2 | `tools/registry.py` 控制流反转——主动 import L1 模块 | 设计 | 工具创建移至 main.py，registry 只管注册 |
| 3 | `agents/prompts.py` L2→L3 向上依赖 | 层级 | `get_shell()` 结果改为 main.py 注入 |
| 4 | 工具分类信息硬编码在 `_LangChainToolAdapter` | 设计 | 改为注册时声明 `read_only` / `destructive` tags |

---

## 1. 删除 Tool ABC，简化 tools/base.py

### 现状

`tools/base.py` 定义了 `Tool[Input, Output]` ABC（30+ 方法），但：
- 0 个 builtin 继承它（全部用 `@tool` 装饰器）
- 唯一子类是 `tools/mcp/adapter.py` 的 `MCPToolAdapter`
- `check_permissions()`、`is_read_only()` 等方法全部空实现，权限由 `permissions/` 独立承担
- `to_langchain_tool()` 用 `nest_asyncio` 做同步包装——绕了一圈回到 LangChain

### 变更

**tools/base.py**:
- 删除 `Tool` ABC 类（保留 `ToolResult`，`StreamingToolExecutor` 仍需要）
- `ToolResult` 去掉泛型参数（`Output` TypeVar 不再需要）
- 删除 `to_langchain_tool()`、`to_openai_schema()` 等转换方法

**tools/__init__.py**:
- 移除 `from LangCode.tools.base import Tool`

**tools/mcp/adapter.py**:
- `MCPToolAdapter` 不再继承 `Tool`，改为返回 `BaseTool` 的工厂函数

**tools/execution.py**:
- 已经是 deferred import `ToolResult`，只需确认兼容

### 不变

- `ToolUseContext`（`tools/context.py`）保留，它是依赖注入载体，与工具接口无关
- `ToolResult` 保留（`data` + `new_messages` + `context_modifier`）
- `StreamingToolExecutor` 保留，只是输入从 `TrackedTool.tool: Tool` 改为 `BaseTool`

---

## 2. 简化 ToolRegistry，删除 adapter

### 现状

```python
# tools/registry.py
class ToolRegistry:
    _tools: dict[str, Tool]   # 存的是 Tool ABC 实例

class _LangChainToolAdapter(Tool):
    # 把 BaseTool 包成 Tool，is_read_only 硬编码在 adapter 里
```

### 变更

```python
# tools/registry.py — 新接口
@dataclass
class ToolEntry:
    tool: BaseTool
    tags: frozenset[str] = frozenset()   # "read_only" | "destructive" | "plan_allowed"

class ToolRegistry:
    _entries: dict[str, ToolEntry]

    def register(self, tool: BaseTool, *, tags: frozenset[str] = frozenset()) -> None:
        ...

    def list_for_mode(self, mode: str) -> list[BaseTool]:
        if mode == "plan":
            return [e.tool for e in self._entries.values() if "read_only" in e.tags or "plan_allowed" in e.tags]
        return [e.tool for e in self._entries.values()]

    def to_langchain_tools(self, mode: str = "build") -> list[BaseTool]:
        return self.list_for_mode(mode)   # 已经是 BaseTool，无需转换
```

- 删除 `_LangChainToolAdapter` 类
- 删除 `register_plan_tools()` / `register_memory_tools()`（职责移到 main.py）

### tags 定义

| tag | 含义 | 示例工具 |
|-----|------|---------|
| `read_only` | 不修改文件系统 | read_file, search_files, grep_content, fetch_api, web_search |
| `destructive` | 不可逆操作 | execute_shell, run_python |
| `plan_allowed` | plan 模式下允许（非只读但安全） | write_todo, update_todo, delegate_explore, delegate_review |
| 无 tag | 默认：写操作，plan 模式禁止 | write_file, edit_file |

---

## 3. 修复控制流反转

### 3.1 registry 不再知道 planning/memory

**删除** `tools/registry.py` 中的：
```python
def register_plan_tools(registry):
    from LangCode.planning.todo_tools import create_todo_tools  # ← 删除

def register_memory_tools(registry, store, manager):
    from LangCode.memory.tools import create_memory_tools      # ← 删除
```

**新增** `main.py` 中：
```python
# 工具注册（main.py 统一编排，registry 不知道 L1 模块的存在）
from LangCode.planning.todo_tools import create_todo_tools
from LangCode.memory.tools import create_memory_tools

registry.register_many(create_todo_tools(), tags=frozenset({"plan_allowed"}))
registry.register_many(create_memory_tools(memory_store, memory_manager),
                       tags=frozenset({"read_only"}))  # memory_search, memory_list 只读
```

### 3.2 agents/prompts.py 不再依赖 tools

**现状**（L2→L3 向上违规）：
```python
# agents/prompts.py:75
def _render_windows_prompt(template: str) -> str:
    from LangCode.tools.builtin.shell import get_shell  # ← L2 import L3
```

**修复**：`get_platform_prompt()` 增加 `bash_path` 参数，由 main.py 传入：
```python
# agents/prompts.py
def get_platform_prompt(bash_path: str | None = None) -> str:
    ...
    if os_name == "windows" and ("{%" in content or "{{" in content):
        content = _render_windows_prompt(content, bash_path)
    ...

def _render_windows_prompt(template: str, bash_path: str | None) -> str:
    # 直接使用 bash_path 参数，不再调用 get_shell()
    if bash_path:
        block, _ = _extract_jinja_block(template, "if bash_path", "else", "endif")
        ...
```

```python
# main.py
from LangCode.tools.builtin.shell import get_shell
platform_prompt = get_platform_prompt(bash_path=get_shell())
```

---

## 4. 涉及文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tools/base.py` | **重写** | 删除 Tool ABC，保留精简的 ToolResult |
| `tools/__init__.py` | 修改 | 移除 Tool re-export |
| `tools/registry.py` | **重写** | ToolEntry + tags，删除 adapter 和 L1 注册函数 |
| `tools/execution.py` | 修改 | TrackedTool.tool 类型从 Tool 改为 BaseTool |
| `tools/mcp/adapter.py` | 修改 | MCPToolAdapter 不再继承 Tool，改工厂函数 |
| `main.py` | 修改 | 补充 todo/memory 工具注册 + bash_path 注入 |
| `agents/prompts.py` | 修改 | get_platform_prompt 增加 bash_path 参数 |
| `ARCHITECTURE_v2.md` | **重写部分章节** | 工具系统、分层规则、对比表，版本升至 v2.1 |

### 不变的文件

- `tools/builtin/*` — 全部保持 `@tool` 装饰器，无需修改
- `tools/context.py` — ToolUseContext 不变
- `tools/ast/*` — AST 工具不变（也用 `@tool`）
- `permissions/*` — 独立模块，不涉及
- `planning/todo_tools.py`、`memory/tools.py` — L1 工具定义不变
- `agents/graph_builder.py`、`agents/router.py` — 不涉及
- `engine/*`、`state/*`、`services/*` — 不涉及

---

## 5. 执行顺序

1. **tools/base.py** — 删除 Tool ABC，精简 ToolResult
2. **tools/registry.py** — 重写为 ToolEntry + tags，删除 adapter 和 L1 函数
3. **tools/__init__.py** — 移除 Tool 引用
4. **tools/execution.py** — 适配新类型
5. **tools/mcp/adapter.py** — 适配新接口
6. **agents/prompts.py** — bash_path 参数注入
7. **main.py** — 补充注册 + bash_path 传入
8. **ARCHITECTURE_v2.md** — 同步更新文档

每步完成后 `uv run python -c "from LangCode.main import create_engine"` 验证 import 不报错。
