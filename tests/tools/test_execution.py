"""tools.execution — StreamingToolExecutor 测试（v2.1: 串行调度）"""

import asyncio
import pytest
from langchain.tools import tool as langchain_tool

from LangCode.tools.registry import ToolRegistry
from LangCode.tools.execution import StreamingToolExecutor, ToolStatus, TrackedTool


# ── 测试工具 ──

@langchain_tool
def fast_read(value: str = "test") -> str:
    """快速只读工具"""
    return f"read:{value}"


@langchain_tool
def slow_write(value: str = "test") -> str:
    """慢速写入工具"""
    import time
    time.sleep(0.05)
    return f"written:{value}"


@langchain_tool
def failing_tool(value: str = "test") -> str:
    """总是失败的工具"""
    raise RuntimeError("tool error")


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(fast_read)
    r.register(slow_write)
    r.register(failing_tool)
    return r


def run_async(gen):
    """将 async generator 转为 list"""
    async def _collect():
        results = []
        async for item in gen:
            results.append(item)
        return results
    return asyncio.run(_collect())


class TestTrackedTool:
    def test_initial_status(self):
        t = TrackedTool(tool_call={"id": "1", "name": "test", "args": {}}, tool=None)
        assert t.status == ToolStatus.QUEUED
        assert t.result is None
        assert t.error is None


class TestStreamingToolExecutor:
    def test_add_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "hello"}})
        assert len(executor._tracked) == 1
        assert executor._tracked[0].tool is not None

    def test_add_unknown_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "nonexistent", "args": {}})
        assert len(executor._tracked) == 1
        assert executor._tracked[0].tool is None

    def test_pending_count(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {}})
        executor.add_tool({"id": "2", "name": "slow_write", "args": {}})
        assert executor.pending_count == 2

    def test_execute_single_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "test"}})

        results = run_async(executor.execute_all())
        assert len(results) == 1
        assert results[0].data == "read:test"

    def test_execute_failing_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "failing_tool", "args": {}})

        results = run_async(executor.execute_all())
        assert len(results) == 1
        assert "错误" in results[0].data

    def test_execute_unknown_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "nonexistent", "args": {}})

        results = run_async(executor.execute_all())
        assert len(results) == 1
        assert "未找到" in results[0].data

    def test_multiple_tools_serial(self, registry):
        """v2.1: 所有工具串行执行"""
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "a"}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {"value": "b"}})
        executor.add_tool({"id": "3", "name": "slow_write", "args": {"value": "c"}})

        results = run_async(executor.execute_all())
        assert len(results) == 3
        # 串行：结果按添加顺序返回
        assert results[0].data == "read:a"
        assert results[1].data == "read:b"
        assert results[2].data == "written:c"

    def test_completed_count(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {}})

        run_async(executor.execute_all())
        assert executor.completed_count == 2
        assert executor.pending_count == 0
