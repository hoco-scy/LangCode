"""tools.base — ToolResult 测试（v2.1: Tool ABC 已删除）"""

import pytest

from LangCode.tools.base import ToolResult


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

    def test_data_any_type(self):
        assert ToolResult(data=42).data == 42
        assert ToolResult(data={"key": "val"}).data == {"key": "val"}
        assert ToolResult(data=None).data is None
