"""engine/query_loop — 查询循环状态机。

参考 Claude Code query.ts 的 queryLoop 设计：
  无限循环 while True
  每次迭代: 预处理 → API调用 → 工具执行 → 决策(Continue/Terminal)

LangCode 的特殊性：
  LangGraph 的 graph.stream() 已经封装了 agent→tools→verify→router 内循环。
  query_loop 作为外层包装，负责：
  1. 上下文压缩检查（每轮开始前）
  2. 图执行（调用 graph.stream）
  3. 错误恢复（API 失败 → 重试/降级/放弃）
  4. Token 预算检查（每轮结束后）
  5. 最大轮次限制
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

from LangCode.shared.logger import get_logger

log = get_logger("engine.query_loop")


class TerminalReason(str, Enum):
    """查询终止原因"""
    COMPLETED = "completed"              # 正常完成（LLM 无 tool_calls）
    MAX_TURNS = "max_turns"              # 达到最大轮次
    TOKEN_BUDGET = "token_budget"        # Token 预算耗尽
    ABORTED_STREAMING = "aborted_streaming"  # 用户中断流式输出
    ABORTED_TOOLS = "aborted_tools"      # 用户中断工具执行
    PROMPT_TOO_LONG = "prompt_too_long"  # 413 且无法恢复
    MODEL_ERROR = "model_error"          # 模型错误且无法恢复


class ContinueReason(str, Enum):
    """继续循环的原因"""
    NEXT_TURN = "next_turn"                        # 正常下一轮
    AUTO_COMPACT_RETRY = "auto_compact_retry"      # 压缩后重试
    MAX_OUTPUT_ESCALATE = "max_output_escalate"    # 升级 max_output_tokens
    MAX_OUTPUT_RECOVERY = "max_output_recovery"    # 注入 recovery message
    FALLBACK_MODEL = "fallback_model"              # 切换 fallback 模型
    TOKEN_BUDGET_CONTINUATION = "token_budget_continuation"  # 预算允许继续


@dataclass
class LoopState:
    """查询循环状态。

    跨多次重试保持状态（recovery state、turn count 等）。
    """
    turn_count: int = 0
    total_usage: dict = field(default_factory=lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
    })
    transition: Optional[ContinueReason] = None
    terminal_reason: Optional[TerminalReason] = None

    # ── 错误恢复状态 ──
    max_output_tokens_override: Optional[int] = None
    max_output_recovery_count: int = 0
    has_attempted_reactive_compact: bool = False
    has_attempted_collapse_drain: bool = False


@dataclass
class LoopResult:
    """查询循环结果"""
    terminal_reason: TerminalReason
    turn_count: int
    total_usage: dict
    error: Optional[str] = None


def check_max_turns(state: LoopState, max_turns: int) -> bool:
    """检查是否超过最大轮次。返回 True 表示应停止。"""
    return state.turn_count >= max_turns


def update_usage(state: LoopState, usage: dict) -> None:
    """累加 token 使用量。"""
    state.total_usage["input_tokens"] += usage.get("input_tokens", 0)
    state.total_usage["output_tokens"] += usage.get("output_tokens", 0)
