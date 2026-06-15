"""ToolRegistry — 工具注册、发现、过滤、Schema 生成。

参考 Claude Code tools.ts 的 getAllBaseTools() 设计：
- 三源工具: 内置(builtin/) + AST(ast/) + MCP(mcp/)
- 按 agent_mode 过滤: plan 模式下只返回只读工具
- 支持动态注册: MCP 工具在运行时动态注册

用法：
    registry = ToolRegistry()
    register_all_builtin_tools(registry)
    register_ast_tools(registry)
    tools = registry.to_langchain_tools("build")  # 获取 LangChain 工具列表
"""

from __future__ import annotations

from typing import Optional, Any

from LangCode.tools.base import Tool
from LangCode.shared.logger import get_logger

log = get_logger("tools.registry")


class ToolRegistry:
    """工具注册中心。

    工具来源:
    - 内置工具: tools/builtin/（file_read, shell, python 等）
    - AST 工具: tools/ast/（ast_info, ast_rename 等）
    - MCP 工具: tools/mcp/（运行时动态注册）
    - 记忆工具: memory/tools.py（memory_save/search/list）
    - Todo 工具: planning/todo_tools.py（write_todo / update_todo / modify_todo）
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._lc_tools_cache: dict[str, list] = {}  # mode → LangChain tools 缓存

    def register(self, tool: Tool) -> None:
        """注册单个工具。
        如果 tool 是 LangChain BaseTool（旧代码），自动适配。"""
        if hasattr(tool, 'name') and hasattr(tool, 'invoke'):
            # LangChain BaseTool 兼容包装
            self._tools[tool.name] = _LangChainToolAdapter(tool)
            log.debug("注册 LangChain 工具: %s", tool.name)
        else:
            self._tools[tool.name] = tool
            log.debug("注册原生工具: %s", tool.name)
        self._lc_tools_cache.clear()

    def register_many(self, tools: list) -> None:
        """批量注册工具。"""
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Optional[Tool]:
        """按名称获取工具。"""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """获取全部已注册工具。"""
        return list(self._tools.values())

    def list_for_mode(self, mode: str) -> list[Tool]:
        """根据权限模式过滤工具列表。

        plan 模式: 只返回只读工具
        其他模式: 返回全部

        Args:
            mode: PermissionMode（"plan", "default", "bypass" 等）

        Returns:
            过滤后的工具列表
        """
        if mode == "plan":
            return [t for t in self._tools.values()
                    if t.is_read_only(None) or getattr(t, 'is_plan_allowed', lambda: False)()]
        return list(self._tools.values())

    def to_langchain_tools(self, mode: str = "build") -> list:
        """转换为 LangChain BaseTool 列表（用于 bind_tools）。

        带缓存：同一 mode 的结果会被缓存，直到有新工具注册。

        Args:
            mode: PermissionMode

        Returns:
            LangChain BaseTool 列表
        """
        if mode in self._lc_tools_cache:
            return self._lc_tools_cache[mode]

        tools = self.list_for_mode(mode)
        lc_tools = []
        for t in tools:
            lc_tools.append(t.to_langchain_tool())
        self._lc_tools_cache[mode] = lc_tools
        return lc_tools

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


class _LangChainToolAdapter(Tool):
    """将 LangChain BaseTool 适配为原生 Tool 接口。

    允许旧代码中使用 @tool 装饰器创建的工具注册到新的 ToolRegistry。
    """

    def __init__(self, lc_tool):
        self._lc_tool = lc_tool
        self.name = lc_tool.name
        self.description = lc_tool.description or ""
        self.input_schema = getattr(lc_tool, 'args_schema', None) or _dummy_schema(self.name)

    async def call(self, args, context):
        result = self._lc_tool.invoke(args.model_dump() if hasattr(args, 'model_dump') else args)
        return ToolResult(data=result)

    def check_permissions(self, args, context):
        return None  # 旧工具：权限由权限系统统一处理

    def is_read_only(self, args):
        return self.name in ("read_file", "search_files", "grep_content", "fetch_api",
                             "memory_search", "memory_list", "plan_show", "web_search")

    def is_plan_allowed(self):
        return self.name in (
            "read_file", "search_files", "grep_content", "fetch_api", "web_search",
            "memory_search", "memory_list",
            "write_todo", "update_todo", "modify_todo",
            "delegate_explore", "delegate_review",
        )

    def to_langchain_tool(self):
        return self._lc_tool


def _dummy_schema(name: str):
    """为没有 args_schema 的工具创建最小 schema"""
    from pydantic import BaseModel, Field
    class DummyInput(BaseModel):
        class Config:
            json_schema_extra = {"description": f"Input for {name}"}
    DummyInput.__name__ = f"{name}Input"
    return DummyInput


# ── 工具注册函数 ──

def register_all_builtin_tools(registry: ToolRegistry) -> None:
    """注册所有内置工具（tools/builtin/）。"""
    from LangCode.tools.builtin import all_tools
    registry.register_many(all_tools)
    log.info("已注册 %d 个内置工具", len(all_tools))


def register_ast_tools(registry: ToolRegistry) -> None:
    """注册 AST 结构化编辑工具（tools/ast/）。"""
    from LangCode.tools.ast import ast_tools
    registry.register_many(ast_tools)
    log.info("已注册 %d 个 AST 工具", len(ast_tools))


def register_plan_tools(registry: ToolRegistry) -> None:
    """注册 write_todo / update_todo / modify_todo 工具。"""
    from LangCode.planning.todo_tools import create_todo_tools
    tools = create_todo_tools()
    registry.register_many(tools)
    log.info("已注册 %d 个 todo 工具", len(tools))


def register_mcp_tools(registry: ToolRegistry) -> None:
    """注册 MCP 工具（从 ~/.langcode/mcp.json 加载）。"""
    try:
        from LangCode.tools.mcp import MCPManager
        mcp = MCPManager()
        status = mcp.connect_all()
        if status["connected"] > 0:
            lc_tools = mcp.create_langchain_tools()
            registry.register_many(lc_tools)
            log.info("已注册 %d 个 MCP 工具", status["connected"])
    except Exception as e:
        log.debug("MCP 工具注册跳过: %s", e)


def register_memory_tools(registry: ToolRegistry, memory_store, memory_manager) -> None:
    """注册记忆工具。"""
    from LangCode.memory.tools import create_memory_tools
    tools = create_memory_tools(memory_store, memory_manager)
    registry.register_many(tools)
    log.info("已注册 %d 个记忆工具", len(tools))
