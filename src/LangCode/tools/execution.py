"""tools.execution — 工具并发调度器。

v2.1 变更：
- 适配 LangChain BaseTool（invoke 替代 call，args_schema 替代 input_schema）
- 权限检查移至外部（permissions/rules.py），不再在工具层调用
- is_concurrency_safe 暂不支持（LangChain BaseTool 无此接口），所有工具串行执行
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any

from LangCode.shared.logger import get_logger

log = get_logger("tools.execution")


class ToolStatus(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    YIELDED = "yielded"


@dataclass
class TrackedTool:
    """跟踪单个工具调用的执行状态。"""
    tool_call: dict          # {"id", "name", "args"}
    tool: Any                # LangChain BaseTool 实例
    status: ToolStatus = ToolStatus.QUEUED
    result: Any = None
    error: Optional[Exception] = None


class StreamingToolExecutor:
    """工具串行调度器。

    v2.1 简化：所有工具串行执行（LangChain BaseTool 无 is_concurrency_safe 接口）。
    未来可通过 tags["concurrent_safe"] 恢复并发支持。

    用法：
        executor = StreamingToolExecutor(tool_registry, context)
        for tc in assistant_msg.tool_calls:
            executor.add_tool(tc)
        async for result in executor.execute_all():
            yield result
    """

    def __init__(self, registry: Any, context: Any = None):
        self._registry = registry
        self._context = context
        self._tracked: list[TrackedTool] = []

    def add_tool(self, tool_call: dict) -> None:
        """添加一个待执行的工具调用。"""
        name = tool_call.get("name", "")
        tool = self._registry.get(name) if self._registry else None
        self._tracked.append(TrackedTool(
            tool_call=tool_call,
            tool=tool,
        ))

    async def execute_all(self):
        """串行执行所有工具。Yields ToolResult 对象。"""
        for tracked in self._tracked:
            result = await self._execute_one(tracked)
            if result is not None:
                yield result

    async def _execute_one(self, tracked: TrackedTool) -> Any:
        """执行单个工具。"""
        tc = tracked.tool_call
        name = tc.get("name", "")
        raw_args = tc.get("args", {})

        if tracked.tool is None:
            log.warning("工具未找到: %s", name)
            return self._make_error_result(tracked, ValueError(f"工具未找到: {name}"))

        tracked.status = ToolStatus.EXECUTING

        try:
            # LangChain BaseTool: invoke(dict) → str
            result_str = await _invoke_tool(tracked.tool, raw_args)
            from LangCode.tools.base import ToolResult
            result = ToolResult(data=result_str)
            tracked.status = ToolStatus.COMPLETED
            tracked.result = result
            return result

        except Exception as e:
            tracked.status = ToolStatus.COMPLETED
            tracked.error = e
            log.error("工具 %s 执行异常: %s", name, e)
            return self._make_error_result(tracked, e)

    def _make_error_result(self, tracked: TrackedTool, error: Exception) -> Any:
        from LangCode.tools.base import ToolResult
        name = tracked.tool_call.get("name", "")
        return ToolResult(data=f"[错误] {name}: {error}")

    def _make_permission_denied(self, tracked: TrackedTool, reason: str) -> Any:
        from LangCode.tools.base import ToolResult
        name = tracked.tool_call.get("name", "")
        return ToolResult(data=f"[权限拒绝] {name}: {reason}")

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tracked if t.status == ToolStatus.QUEUED)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self._tracked if t.status == ToolStatus.COMPLETED)


async def _invoke_tool(tool, args: dict) -> str:
    """调用 LangChain BaseTool，兼容同步和异步。"""
    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(args)
    # 同步 fallback
    return tool.invoke(args)
