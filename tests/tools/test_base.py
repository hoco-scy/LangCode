"""tools.base — Tool 抽象接口测试"""

import pytest
from pydantic import BaseModel, Field

from LangCode.tools.base import Tool, ToolResult


# ── 测试用具 ──

class DummyInput(BaseModel):
    file_path: str = Field(description="文件路径")


class DummyTool(Tool[DummyInput, str]):
    name = "dummy_read"
    description = "读取文件（测试用）"
    input_schema = DummyInput

    async def call(self, args, context):
        return ToolResult(data=f"content of {args.file_path}")

    def check_permissions(self, args, context):
        return None  # 测试中跳过

    def is_read_only(self, args):
        return True

    def is_concurrency_safe(self, args):
        return True


class WriteTool(Tool[DummyInput, str]):
    name = "dummy_write"
    description = "写入文件（测试用）"
    input_schema = DummyInput

    async def call(self, args, context):
        return ToolResult(data="written")

    def check_permissions(self, args, context):
        return None

    def is_destructive(self, args):
        return True


class TestToolResult:
    def test_basic(self):
        r = ToolResult(data="hello")
        assert r.data == "hello"
        assert r.new_messages == []
        assert r.context_modifier is None

    def test_with_messages(self):
        from langchain_core.messages import SystemMessage
        r = ToolResult(data="x", new_messages=[SystemMessage(content="extra")])
        assert len(r.new_messages) == 1

    def test_with_context_modifier(self):
        mod = lambda ctx: ctx
        r = ToolResult(data="x", context_modifier=mod)
        assert r.context_modifier is mod


class TestToolClassification:
    def test_read_only_tool(self):
        t = DummyTool()
        args = DummyInput(file_path="/tmp/test")
        assert t.is_read_only(args) is True
        assert t.is_concurrency_safe(args) is True
        assert t.is_destructive(args) is False

    def test_destructive_tool(self):
        t = WriteTool()
        args = DummyInput(file_path="/tmp/test")
        assert t.is_destructive(args) is True
        assert t.is_read_only(args) is False


class TestToolCall:
    def test_call_returns_result(self):
        import asyncio
        t = DummyTool()
        result = asyncio.run(t.call(DummyInput(file_path="test.py"), None))
        assert isinstance(result, ToolResult)
        assert "test.py" in result.data


class TestToolSchemas:
    def test_to_openai_schema(self):
        t = DummyTool()
        schema = t.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "dummy_read"
        assert "parameters" in schema["function"]
        assert "file_path" in str(schema["function"]["parameters"])

    def test_validate_input_default_returns_empty(self):
        t = DummyTool()
        errors = t.validate_input(DummyInput(file_path="test.py"), None)
        assert errors == []
