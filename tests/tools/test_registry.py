"""tools.registry — ToolRegistry 测试（v2.1: ToolEntry + tags）"""

import pytest
from langchain.tools import tool as langchain_tool
from pydantic import BaseModel, Field

from LangCode.tools.registry import (
    ToolRegistry, TAG_READ_ONLY, TAG_DESTRUCTIVE, TAG_PLAN_ALLOWED,
)


# ── 测试工具（LangChain @tool） ──

@langchain_tool
def test_read(path: str = ".") -> str:
    """只读工具"""
    return "read"


@langchain_tool
def test_write(path: str = ".") -> str:
    """写入工具"""
    return "written"


@langchain_tool
def test_plan_action(task: str = "") -> str:
    """计划工具（非只读，但 plan 模式允许）"""
    return "done"


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(test_read, tags=frozenset({TAG_READ_ONLY}))
    r.register(test_write, tags=frozenset({TAG_DESTRUCTIVE}))
    r.register(test_plan_action, tags=frozenset({TAG_PLAN_ALLOWED}))
    return r


class TestToolRegistry:
    def test_register_and_get(self, registry):
        assert "test_read" in registry
        assert "test_write" in registry
        assert registry.get("nonexistent") is None

    def test_get_returns_basetool(self, registry):
        tool = registry.get("test_read")
        assert hasattr(tool, "invoke")
        assert tool.name == "test_read"

    def test_list_all(self, registry):
        tools = registry.list_all()
        assert len(tools) == 3

    def test_list_for_mode_build_returns_all(self, registry):
        tools = registry.list_for_mode("build")
        assert len(tools) == 3

    def test_list_for_mode_plan_filters_by_tags(self, registry):
        tools = registry.list_for_mode("plan")
        names = {t.name for t in tools}
        # read_only + plan_allowed 通过，destructive 被过滤
        assert "test_read" in names
        assert "test_plan_action" in names
        assert "test_write" not in names

    def test_register_many(self):
        r = ToolRegistry()
        r.register_many([test_read, test_write], tags=frozenset({TAG_READ_ONLY}))
        assert r.tool_count == 2

    def test_register_many_default_empty_tags(self):
        r = ToolRegistry()
        r.register_many([test_read])
        assert r.tool_count == 1

    def test_to_langchain_tools_returns_basetool_list(self, registry):
        lc_tools = registry.to_langchain_tools("build")
        assert isinstance(lc_tools, list)
        assert len(lc_tools) == 3
        # 每个元素都是 BaseTool
        for t in lc_tools:
            assert hasattr(t, "invoke")

    def test_to_langchain_tools_plan_filters(self, registry):
        lc_tools = registry.to_langchain_tools("plan")
        assert len(lc_tools) == 2

    def test_cache_cleared_on_register(self, registry):
        # 预热缓存
        registry.to_langchain_tools("build")
        assert "build" in registry._cache
        # 注册新工具后缓存应清空
        @langchain_tool
        def new_tool() -> str:
            """新工具"""
            return "new"
        registry.register(new_tool)
        assert "build" not in registry._cache

    def test_empty_registry(self):
        r = ToolRegistry()
        assert r.tool_count == 0
        assert r.list_all() == []
        assert r.to_langchain_tools("build") == []
        assert r.to_langchain_tools("plan") == []
