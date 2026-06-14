"""tools.execution — StreamingToolExecutor 测试"""

import asyncio
import pytest
from pydantic import BaseModel, Field

from LangCode.tools.base import Tool, ToolResult
from LangCode.tools.registry import ToolRegistry
from LangCode.tools.execution import StreamingToolExecutor, ToolStatus, TrackedTool


# ── 测试工具 ──

class DummyInput(BaseModel):
    value: str = Field(default="test")


class FastReadTool(Tool[DummyInput, str]):
    name = "fast_read"
    description = "快速只读工具"
    input_schema = DummyInput

    async def call(self, args, context):
        return ToolResult(data=f"read:{args.value}")

    def check_permissions(self, args, context):
        return None

    def is_read_only(self, args):
        return True

    def is_concurrency_safe(self, args):
        return True


class SlowWriteTool(Tool[DummyInput, str]):
    name = "slow_write"
    description = "慢速写入工具"
    input_schema = DummyInput

    async def call(self, args, context):
        await asyncio.sleep(0.05)
        return ToolResult(data=f"written:{args.value}")

    def check_permissions(self, args, context):
        return None

    def is_destructive(self, args):
        return True


class FailingTool(Tool[DummyInput, str]):
    name = "failing"
    description = "总是失败的工具"
    input_schema = DummyInput

    async def call(self, args, context):
        raise RuntimeError("tool error")

    def check_permissions(self, args, context):
        return None


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(FastReadTool())
    r.register(SlowWriteTool())
    r.register(FailingTool())
    return r


# ── 辅助：运行异步生成器 ──

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
        executor.add_tool({"id": "1", "name": "failing", "args": {}})

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
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "fast_read", "args": {"value": "a"}})
        executor.add_tool({"id": "2", "name": "fast_read", "args": {"value": "b"}})

        results = run_async(executor.execute_all())
        assert len(results) == 2
        values = {r.data for r in results}
        assert values == {"read:a", "read:b"}

    def test_serial_execution(self, registry):
        executor = StreamingToolExecutor(registry)
        executor.add_tool({"id": "1", "name": "slow_write", "args": {"value": "x"}})
        executor.add_tool({"id": "2", "name": "slow_write", "args": {"value": "y"}})

        results = run_async(executor.execute_all())
        assert len(results) == 2

    def test_mixed_partition(self, registry):
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
        # fast_read (concurrent) + fast_read (concurrent) → group 1 (concurrent)
        # slow_write (serial) → group 2 (serial)
        # fast_read (concurrent) → group 3 (concurrent)
        assert len(partitions) == 3
        assert partitions[0]["concurrent"] is True
        assert len(partitions[0]["tools"]) == 2
        assert partitions[1]["concurrent"] is False
        assert len(partitions[1]["tools"]) == 1
        assert partitions[2]["concurrent"] is True
        assert len(partitions[2]["tools"]) == 1


class TestPermissionIntegration:
    def test_permission_denied_blocks_execution(self, registry):
        from LangCode.permissions.model import PermissionResult
        from LangCode.tools.context import ToolUseContext

        class DeniedTool(Tool[DummyInput, str]):
            name = "denied_tool"
            description = "会被拒绝的工具"
            input_schema = DummyInput

            async def call(self, args, context):
                return ToolResult(data="should not reach")

            def check_permissions(self, args, context):
                return PermissionResult.deny("测试拒绝")

        registry.register(DeniedTool())
        context = ToolUseContext(
            session_id="test",
            agent_id="test",
            workspace_dir="/tmp",
            model_name="test-model",
            permission_mode="default",
        )
        executor = StreamingToolExecutor(registry, context=context)
        executor.add_tool({"id": "1", "name": "denied_tool", "args": {}})

        results = run_async(executor.execute_all())
        assert len(results) == 1
        assert "权限拒绝" in results[0].data
