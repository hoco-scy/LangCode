"""tools.registry — 工具注册中心测试"""

import pytest
from pydantic import BaseModel, Field

from LangCode.tools.base import Tool, ToolResult
from LangCode.tools.registry import ToolRegistry


# ── 测试用具 ──

class DummyInput(BaseModel):
    path: str = Field(default=".")


class ReadOnlyTool(Tool[DummyInput, str]):
    name = "test_read"
    description = "只读工具"
    input_schema = DummyInput

    async def call(self, args, context):
        return ToolResult(data="read")

    def check_permissions(self, args, context):
        return None

    def is_read_only(self, args):
        return True

    def is_concurrency_safe(self, args):
        return True


class WriteTool(Tool[DummyInput, str]):
    name = "test_write"
    description = "写入工具"
    input_schema = DummyInput

    async def call(self, args, context):
        return ToolResult(data="written")

    def check_permissions(self, args, context):
        return None

    def is_destructive(self, args):
        return True


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(ReadOnlyTool())
    r.register(WriteTool())
    return r


class TestToolRegistry:
    def test_register_and_get(self, registry):
        assert "test_read" in registry
        assert "test_write" in registry
        assert registry.get("nonexistent") is None

    def test_list_all(self, registry):
        tools = registry.list_all()
        assert len(tools) == 2

    def test_list_for_mode_build(self, registry):
        tools = registry.list_for_mode("build")
        assert len(tools) == 2

    def test_list_for_mode_plan(self, registry):
        tools = registry.list_for_mode("plan")
        # plan 模式只返回只读工具
        assert len(tools) == 1
        assert tools[0].name == "test_read"

    def test_register_many(self):
        r = ToolRegistry()
        r.register_many([ReadOnlyTool(), WriteTool()])
        assert r.tool_count == 2

    def test_to_langchain_tools_returns_list(self, registry):
        """to_langchain_tools 应返回列表（不崩溃）"""
        lc_tools = registry.to_langchain_tools("build")
        assert isinstance(lc_tools, list)
        assert len(lc_tools) == 2

    def test_to_langchain_tools_plan_filters(self, registry):
        lc_tools = registry.to_langchain_tools("plan")
        assert len(lc_tools) == 1
