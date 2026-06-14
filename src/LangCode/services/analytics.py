"""services.analytics — 遥测数据收集与追踪。

参考 Claude Code bootstrap/state.ts 的 AnalyticsTracker 设计：
- 关键路径计时（启动、API 调用、工具执行）
- Token 消耗追踪
- 压缩触发频率 + 成功率
- 工具调用成功率 + 耗时分布
- 断路器触发次数

数据驱动的优化决策，不靠猜测。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("services.analytics")


@dataclass
class _TimingRecord:
    """单次计时记录"""
    phase: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)


class AnalyticsTracker:
    """遥测数据追踪器。

    全局单例，在 main.py 中初始化。
    图节点和工具执行器通过 get_analytics() 获取。

    用法：
        tracker = AnalyticsTracker()
        with tracker.time_api_call("mimo-v2.5-pro") as ctx:
            response = llm.invoke(messages)
            ctx.record_tokens(input_tokens=100, output_tokens=50)
    """

    def __init__(self):
        self._session_started_at: float = time.time()
        self._startup_phases: list[_TimingRecord] = []
        self._api_calls: list[dict] = []
        self._tool_calls: list[dict] = []
        self._compact_events: list[dict] = []
        self._error_events: list[dict] = []
        self._total_tokens: int = 0

    # ── 启动计时 ──

    def record_startup_phase(self, phase: str, duration_ms: float) -> None:
        """记录启动阶段耗时。"""
        self._startup_phases.append(_TimingRecord(phase=phase, duration_ms=duration_ms))
        log.debug("启动阶段 %s: %.1fms", phase, duration_ms)

    # ── API 调用追踪 ──

    def record_api_call(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: float = 0,
        cache_hit: bool = False,
    ) -> None:
        """记录一次 API 调用。"""
        total = input_tokens + output_tokens
        self._total_tokens += total
        self._api_calls.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "timestamp": time.time(),
        })

    class _ApiCallContext:
        """API 调用计时上下文管理器"""
        def __init__(self, tracker: "AnalyticsTracker", model: str):
            self._tracker = tracker
            self._model = model
            self._start: float = 0
            self._input_tokens: int = 0
            self._output_tokens: int = 0
            self._cache_hit: bool = False

        def __enter__(self):
            self._start = time.monotonic()
            return self

        def __exit__(self, *_):
            duration_ms = (time.monotonic() - self._start) * 1000
            self._tracker.record_api_call(
                model=self._model,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                duration_ms=duration_ms,
                cache_hit=self._cache_hit,
            )

        def record_tokens(self, input_tokens: int = 0, output_tokens: int = 0,
                          cache_hit: bool = False) -> None:
            self._input_tokens = input_tokens
            self._output_tokens = output_tokens
            self._cache_hit = cache_hit

    def time_api_call(self, model: str) -> _ApiCallContext:
        """API 调用计时上下文管理器。"""
        return self._ApiCallContext(self, model)

    # ── 工具调用追踪 ──

    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float = 0,
    ) -> None:
        """记录一次工具调用。"""
        self._tool_calls.append({
            "tool_name": tool_name,
            "success": success,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

    class _ToolCallContext:
        """工具调用计时上下文管理器"""
        def __init__(self, tracker: "AnalyticsTracker", tool_name: str):
            self._tracker = tracker
            self._tool_name = tool_name
            self._start: float = 0
            self._success: bool = True

        def __enter__(self):
            self._start = time.monotonic()
            return self

        def __exit__(self, exc_type, *_):
            duration_ms = (time.monotonic() - self._start) * 1000
            if exc_type is not None:
                self._success = False
            self._tracker.record_tool_call(
                tool_name=self._tool_name,
                success=self._success,
                duration_ms=duration_ms,
            )

        def mark_failure(self) -> None:
            self._success = False

    def time_tool_call(self, tool_name: str) -> _ToolCallContext:
        """工具调用计时上下文管理器。"""
        return self._ToolCallContext(self, tool_name)

    # ── 压缩事件 ──

    def record_compact(
        self,
        strategy: str,
        tokens_before: int,
        tokens_after: int,
        success: bool = True,
    ) -> None:
        """记录一次上下文压缩事件。"""
        self._compact_events.append({
            "strategy": strategy,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "success": success,
            "timestamp": time.time(),
        })

    # ── 错误事件 ──

    def record_error(self, error_type: str, recovered: bool) -> None:
        """记录一次错误事件。"""
        self._error_events.append({
            "error_type": error_type,
            "recovered": recovered,
            "timestamp": time.time(),
        })

    # ── 快照 ──

    def get_snapshot(self) -> dict:
        """获取当前遥测快照。"""
        session_duration = time.time() - self._session_started_at
        return {
            "session_duration_s": round(session_duration, 1),
            "total_api_calls": len(self._api_calls),
            "total_tool_calls": len(self._tool_calls),
            "total_tokens": self._total_tokens,
            "total_compact_events": len(self._compact_events),
            "total_errors": len(self._error_events),
            "recovered_errors": sum(1 for e in self._error_events if e["recovered"]),
            "startup_phases": [
                {"phase": r.phase, "ms": round(r.duration_ms, 1)}
                for r in self._startup_phases
            ],
            "tool_success_rate": (
                sum(1 for t in self._tool_calls if t["success"]) / max(len(self._tool_calls), 1)
            ),
        }


# ── 全局单例 ──
_analytics: Optional[AnalyticsTracker] = None


def init_analytics() -> AnalyticsTracker:
    """初始化全局 AnalyticsTracker。"""
    global _analytics
    _analytics = AnalyticsTracker()
    return _analytics


def get_analytics() -> AnalyticsTracker:
    """获取全局 AnalyticsTracker。"""
    if _analytics is None:
        return init_analytics()
    return _analytics
