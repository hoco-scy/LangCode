"""tools.execution — 工具并发调度器。

参考 Claude Code StreamingToolExecutor 状态机:
  queued → executing → completed → yielded

分区策略:
  1. 按 is_concurrency_safe 分组
  2. 并发安全组 → asyncio.gather 并行执行
  3. 非并发安全 → 逐个串行执行
  4. Bash 工具失败 → 取消正在运行的兄弟工具
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
    tool: Any                # Tool 实例
    status: ToolStatus = ToolStatus.QUEUED
    is_concurrency_safe: bool = False
    result: Any = None       # ToolResult
    error: Optional[Exception] = None


class StreamingToolExecutor:
    """工具并发调度器。

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

        is_safe = False
        if tool:
            try:
                is_safe = tool.is_concurrency_safe(tool_call.get("args", {}))
            except Exception:
                pass

        self._tracked.append(TrackedTool(
            tool_call=tool_call,
            tool=tool,
            is_concurrency_safe=is_safe,
        ))

    async def execute_all(self):
        """按分区策略执行所有工具。

        分区 → [并发组] → [串行1] → [串行2] → ...

        Yields:
            ToolResult 对象
        """
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

        策略：连续的并发安全工具分为一组，非并发安全工具各自独立。
        """
        groups: list[dict] = []
        current_concurrent: list[TrackedTool] = []

        for tracked in self._tracked:
            if tracked.is_concurrency_safe:
                current_concurrent.append(tracked)
            else:
                # 遇到非并发安全 → 先结束当前并发组
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
                # 构造错误结果
                yield self._make_error_result(tracked, result)
            elif result is not None:
                tracked.result = result
                tracked.status = ToolStatus.COMPLETED
                yield result

    async def _execute_one(self, tracked: TrackedTool) -> Any:
        """执行单个工具：权限检查 → 执行 → 结果。"""
        tc = tracked.tool_call
        name = tc.get("name", "")
        raw_args = tc.get("args", {})
        call_id = tc.get("id", "")

        if tracked.tool is None:
            log.warning("工具未找到: %s", name)
            return self._make_error_result(tracked, ValueError(f"工具未找到: {name}"))

        tracked.status = ToolStatus.EXECUTING

        try:
            # 将 dict 转为 Pydantic 模型
            schema = getattr(tracked.tool, "input_schema", None)
            if schema and isinstance(raw_args, dict):
                args = schema(**raw_args)
            else:
                args = raw_args

            # 权限检查
            if self._context and hasattr(tracked.tool, "check_permissions"):
                from LangCode.permissions.model import PermissionResult
                perm = tracked.tool.check_permissions(args, self._context)
                if perm and hasattr(perm, "behavior"):
                    if perm.behavior == "deny":
                        log.info("权限拒绝: %s — %s", name, perm.reason)
                        return self._make_permission_denied(tracked, perm.reason)

            # 执行
            result = await tracked.tool.call(args, self._context)
            tracked.status = ToolStatus.COMPLETED
            tracked.result = result
            return result

        except Exception as e:
            tracked.status = ToolStatus.COMPLETED
            tracked.error = e
            log.error("工具 %s 执行异常: %s", name, e)
            return self._make_error_result(tracked, e)

    def _make_error_result(self, tracked: TrackedTool, error: Exception) -> Any:
        """构造错误结果。"""
        from LangCode.tools.base import ToolResult
        name = tracked.tool_call.get("name", "")
        call_id = tracked.tool_call.get("id", "")
        return ToolResult(
            data=f"[错误] {name}: {error}",
            new_messages=[],
        )

    def _make_permission_denied(self, tracked: TrackedTool, reason: str) -> Any:
        """构造权限拒绝结果。"""
        from LangCode.tools.base import ToolResult
        name = tracked.tool_call.get("name", "")
        return ToolResult(
            data=f"[权限拒绝] {name}: {reason}",
            new_messages=[],
        )

    @property
    def pending_count(self) -> int:
        """待执行工具数。"""
        return sum(1 for t in self._tracked if t.status == ToolStatus.QUEUED)

    @property
    def completed_count(self) -> int:
        """已完成工具数。"""
        return sum(1 for t in self._tracked if t.status == ToolStatus.COMPLETED)
