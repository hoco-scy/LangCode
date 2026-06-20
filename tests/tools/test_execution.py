"""tools.execution — StreamingToolExecutor 测试（v2.1: tags 驱动并发）"""

import asyncio
import pytest
from langchain.tools import tool as langchain_tool

from LangCode.tools.registry import ToolRegistry, TAG_READ_ONLY, TAG_CONCURRENT_SAFE
from LangCode.tools.execution import StreamingToolExecutor, ToolStatus, TrackedTool


# ── 测试工具 ──

@langchain_tool
def fast_read(value: str = "test") -> str:
    """快速只读并发安全工具"""
    return f"read:{value}"


@langchain_tool
def slow_write(value: str = "test") -> str:
    """慢速写入工具（非并发安全）"""
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
    r.register(fast_read, tags=frozenset({TAG_READ_ONLY, TAG_CONCURRENT_SAFE}))
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

    def test_concurrency_safe_flag(self):
        t = TrackedTool(tool_call={}, tool=None, is_concurrency_safe=True)
        assert t.is_concurrency_safe is True


class TestStreamingToolExecutor:
    def test_add_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "hello"}})
        assert len(executor._tracked) == 1
        assert executor._tracked[0].tool is not None
        assert executor._tracked[0].is_concurrency_safe is True

    def test_add_non_concurrent_tool(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "slow_write", "args": {}})
        assert executor._tracked[0].is_concurrency_safe is False

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

    def test_concurrent_execution(self, registry):
        """并发安全工具应并行执行"""
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "a"}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {"value": "b"}})

        results = run_async(executor.execute_all())
        assert len(results) == 2
        values = {r.data for r in results}
        assert values == {"read:a", "read:b"}

    def test_serial_execution(self, registry):
        """非并发安全工具应串行执行"""
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "slow_write", "args": {"value": "x"}})
        executor.add_tool({"id": "2", "name": "slow_write", "args": {"value": "y"}})

        results = run_async(executor.execute_all())
        assert len(results) == 2

    def test_mixed_partition(self, registry):
        """混合：并发组 + 串行"""
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "a"}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {"value": "b"}})
        executor.add_tool({"id": "3", "name": "slow_write", "args": {"value": "c"}})

        results = run_async(executor.execute_all())
        assert len(results) == 3

    def test_partition_logic(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {}})
        executor.add_tool({"id": "3", "name": "slow_write", "args": {}})
        executor.add_tool({"id": "4", "name": "fast_read", "args": {}})

        partitions = executor._partition()
        # fast_read (concurrent) x2 → group 1
        # slow_write (serial) → group 2
        # fast_read (concurrent) x1 → group 3
        assert len(partitions) == 3
        assert partitions[0]["concurrent"] is True
        assert len(partitions[0]["tools"]) == 2
        assert partitions[1]["concurrent"] is False
        assert len(partitions[1]["tools"]) == 1
        assert partitions[2]["concurrent"] is True
        assert len(partitions[2]["tools"]) == 1

    def test_completed_count(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {}})

        run_async(executor.execute_all())
        assert executor.completed_count == 2
        assert executor.pending_count == 0
