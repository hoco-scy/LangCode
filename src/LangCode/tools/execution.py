"""tools.execution — 工具并发调度器。

分区策略（参考 Claude Code StreamingToolExecutor）:
  1. 按 TAG_CONCURRENT_SAFE 分组
  2. 并发安全组 → asyncio.gather 并行执行
  3. 非并发安全 → 逐个串行执行

v2.1 变更：
- 适配 LangChain BaseTool（ainvoke/invoke 替代 call）
- is_concurrency_safe 由 ToolRegistry.is_concurrent_safe(tags) 驱动
- 权限检查移至外部（permissions/rules.py）
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
    is_concurrency_safe: bool = False
    result: Any = None
    error: Optional[Exception] = None


class StreamingToolExecutor:
    """工具并发调度器。

    分区 → [并发组] → parallel → [串行1] → serial → [串行2] → ...

    用法：
        executor = StreamingToolExecutor(registry, context)
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
        is_safe = (
            self._registry.is_concurrent_safe(name)
            if self._registry and hasattr(self._registry, "is_concurrent_safe")
            else False
        )
        self._tracked.append(TrackedTool(
            tool_call=tool_call,
            tool=tool,
            is_concurrency_safe=is_safe,
        ))

    async def execute_all(self):
        """按分区策略执行所有工具。Yields ToolResult 对象。"""
        partitions = self._partition()

        for group in partitions:
            if group["concurrent"]:
                async for result in self._execute_concurrent(group["tools"]):
                    yield result
            else:
                for tracked in group["tools"]:
                    result = await self._execute_one(tracked)
                    if result is not None:
                        yield result

    def _partition(self) -> list[dict]:
        """将 tracked tools 分为并发组和串行组。

        连续的并发安全工具分为一组，非并发安全工具各自独立。
        """
        groups: list[dict] = []
        current_concurrent: list[TrackedTool] = []

        for tracked in self._tracked:
            if tracked.is_concurrency_safe:
                current_concurrent.append(tracked)
            else:
                if current_concurrent:
                    groups.append({"concurrent": True, "tools": current_concurrent})
                    current_concurrent = []
                groups.append({"concurrent": False, "tools": [tracked]})

        if current_concurrent:
            groups.append({"concurrent": True, "tools": current_concurrent})

        return groups

    async def _execute_concurrent(self, tools: list[TrackedTool]):
        """并发执行一组工具。"""
        tasks = []
        for tracked in tools:
            tracked.status = ToolStatus.EXECUTING
            tasks.append(self._execute_one(tracked))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for tracked, result in zip(tools, results):
            if isinstance(result, Exception):
                tracked.error = result
                tracked.status = ToolStatus.COMPLETED
                log.error("并发工具 %s 执行失败: %s", tracked.tool_call["name"], result)
                yield self._make_error_result(tracked, result)
            elif result is not None:
                tracked.result = result
                tracked.status = ToolStatus.COMPLETED
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
    return tool.invoke(args)
