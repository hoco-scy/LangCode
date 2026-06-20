"""ToolRegistry — 工具注册、发现、过滤。

v2.1 变更：
- 统一使用 LangChain BaseTool，删除 Tool ABC 和 _LangChainToolAdapter
- 工具分类改为注册时声明 tags（read_only / destructive / plan_allowed）
- 删除 register_plan_tools / register_memory_tools（改由 main.py 注入）

用法：
    registry = ToolRegistry()
    register_all_builtin_tools(registry)
    register_ast_tools(registry)
    registry.register(todo_tool, tags=frozenset({"plan_allowed"}))
    tools = registry.to_langchain_tools("plan")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any

from langchain_core.tools import BaseTool

from LangCode.shared.logger import get_logger

log = get_logger("tools.registry")


@dataclass
class ToolEntry:
    """工具注册条目 — BaseTool + 分类标签。"""
    tool: BaseTool
    tags: frozenset[str] = field(default_factory=frozenset)


# ── 预定义 tags ──
TAG_READ_ONLY = "read_only"
TAG_DESTRUCTIVE = "destructive"
TAG_PLAN_ALLOWED = "plan_allowed"
TAG_CONCURRENT_SAFE = "concurrent_safe"   # 可与其他 concurrent_safe 工具并行执行

# 只读工具默认 tag 集合（main.py 中使用）
DEFAULT_READ_ONLY_TAGS = frozenset({TAG_READ_ONLY})
DEFAULT_PLAN_ALLOWED_TAGS = frozenset({TAG_PLAN_ALLOWED})


class ToolRegistry:
    """工具注册中心。

    职责：注册工具 + 按权限模式过滤。不做工具创建。
    工具创建由 main.py（composition root）编排。
    """

    def __init__(self):
        self._entries: dict[str, ToolEntry] = {}
        self._cache: dict[str, list[BaseTool]] = {}

    def register(
        self,
        tool: BaseTool,
        *,
        tags: frozenset[str] = frozenset(),
    ) -> None:
        """注册单个工具。"""
        self._entries[tool.name] = ToolEntry(tool=tool, tags=tags)
        self._cache.clear()
        log.debug("注册工具: %s (tags=%s)", tool.name, tags or "{}")

    def register_many(
        self,
        tools: list[BaseTool],
        *,
        tags: frozenset[str] = frozenset(),
    ) -> None:
        """批量注册工具（共享相同 tags）。"""
        for t in tools:
            self.register(t, tags=tags)

    def get(self, name: str) -> Optional[BaseTool]:
        """按名称获取工具。"""
        entry = self._entries.get(name)
        return entry.tool if entry else None

    def list_all(self) -> list[BaseTool]:
        """获取全部已注册工具。"""
        return [e.tool for e in self._entries.values()]

    def list_for_mode(self, mode: str) -> list[BaseTool]:
        """根据权限模式过滤工具列表。

        plan 模式: 只返回 read_only 或 plan_allowed 的工具
        其他模式: 返回全部
        """
        if mode == "plan":
            return [
                e.tool for e in self._entries.values()
                if TAG_READ_ONLY in e.tags or TAG_PLAN_ALLOWED in e.tags
            ]
        return [e.tool for e in self._entries.values()]

    def to_langchain_tools(self, mode: str = "build") -> list[BaseTool]:
        """获取 LangChain BaseTool 列表（用于 bind_tools）。带缓存。"""
        if mode in self._cache:
            return self._cache[mode]
        tools = self.list_for_mode(mode)
        self._cache[mode] = tools
        return tools

    @property
    def tool_count(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def is_concurrent_safe(self, name: str) -> bool:
        """检查工具是否标记为并发安全。"""
        entry = self._entries.get(name)
        return TAG_CONCURRENT_SAFE in entry.tags if entry else False


# ── 工具注册函数（只保留不依赖 L1 的） ──

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
