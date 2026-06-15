"""engine.recovery — 错误恢复链。

参考 Claude Code query.ts 的错误处理策略：

1. max_output_tokens 截断:
   a. escalate: 8k → 64k（如果 capability 允许）
   b. recovery message: 注入 "Output token limit hit. Resume directly."
      （最多 MAX_RECOVERY 次，措辞精心设计——"no apology, no recap"）

2. 413 prompt_too_long:
   a. collapse_drain: 清除暂存的 collapse → 释放空间（只尝试一次）
   b. reactive_compact: 执行全量上下文压缩
   c. error_surface: 压缩后仍超限 → 向用户展示错误

3. 模型不可用:
   a. switch_to_fallback: 切换到备用模型
   b. strip_thinking_signatures: 降级时剥离 protected thinking blocks

被扣留（withheld）的消息设计：
  可恢复的错误消息在恢复过程中不 yield 给调用方。
  只有恢复手段用尽后才表面化。防止 SDK 消费者在恢复成功时收到虚假错误信号。
"""

from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from enum import Enum

from LangCode.shared.logger import get_logger

log = get_logger("engine.recovery")


# ── 常量 ──
MAX_OUTPUT_TOKENS_RECOVERY_LIMIT: int = 3
ESCALATED_MAX_TOKENS: int = 64_000


class RecoveryAction(str, Enum):
    """恢复动作"""
    ESCALATE = "escalate"          # 升级 max_output_tokens
    RECOVERY_MESSAGE = "recovery"  # 注入恢复消息
    COLLAPSE_DRAIN = "collapse"    # 清除 collapse
    COMPACT = "compact"            # 全量压缩
    FALLBACK_MODEL = "fallback"    # 切换 fallback 模型
    GIVE_UP = "give_up"           # 放弃恢复


@dataclass
class RecoveryState:
    """恢复状态（跨多次重试保持）"""
    max_output_tokens_override: Optional[int] = None
    max_output_recovery_count: int = 0
    has_attempted_reactive_compact: bool = False
    has_attempted_collapse_drain: bool = False
    last_recovery_action: Optional[RecoveryAction] = None


def classify_error(error: Exception) -> str:
    """将异常分类为错误类型。

    Returns:
        "max_output" | "prompt_too_long" | "model_unavailable" | "rate_limit" | "unknown"
    """
    err_str = str(error).lower()
    err_type = type(error).__name__

    if "max_output" in err_str or "max_tokens" in err_str:
        return "max_output"
    if "413" in err_str or "too long" in err_str or "prompt_too_long" in err_str:
        return "prompt_too_long"
    if "unavailable" in err_str or "overloaded" in err_str or "503" in err_str:
        return "model_unavailable"
    if "rate" in err_str or "429" in err_str:
        return "rate_limit"
    return "unknown"


def try_recover(
    state: RecoveryState,
    error: Exception,
    llm=None,
    compactor=None,
    messages: list = None,
) -> tuple[RecoveryAction, list]:
    """尝试从错误中恢复。

    Args:
        state: 恢复状态（跨重试保持）
        error: 发生的异常
        llm: LLMClient（fallback 时需要）
        compactor: ContextCompactor（compact 时需要）
        messages: 当前消息列表

    Returns:
        (RecoveryAction, new_messages)
        - RecoveryAction: 建议的恢复动作
        - new_messages: 更新后的消息列表（注入 recovery message 等）

    如果 action == GIVE_UP，表示无法恢复。
    """
    from langchain_core.messages import HumanMessage

    error_type = classify_error(error)
    log.info("尝试恢复: error_type=%s, action=%s",
             error_type, state.last_recovery_action)

    # ── max_output_tokens ──
    if error_type == "max_output":
        # a. escalate 8k → 64k
        if state.max_output_tokens_override is None:
            state.max_output_tokens_override = ESCALATED_MAX_TOKENS
            state.last_recovery_action = RecoveryAction.ESCALATE
            log.info("升级 max_output_tokens → %d", ESCALATED_MAX_TOKENS)
            return RecoveryAction.ESCALATE, messages or []

        # b. recovery message（最多 MAX_RECOVERY 次）
        if state.max_output_recovery_count < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT:
            recovery_msg = HumanMessage(
                content=(
                    "Output token limit hit. Resume directly — "
                    "no apology, no recap. "
                    "Pick up mid-thought if that is where the cut happened. "
                    "Break remaining work into smaller pieces."
                ),
            )
            state.max_output_recovery_count += 1
            state.last_recovery_action = RecoveryAction.RECOVERY_MESSAGE
            log.info("注入 recovery message (%d/%d)",
                     state.max_output_recovery_count, MAX_OUTPUT_TOKENS_RECOVERY_LIMIT)
            updated = list(messages or []) + [recovery_msg]
            return RecoveryAction.RECOVERY_MESSAGE, updated

        # 恢复次数耗尽
        log.warning("max_output 恢复次数耗尽 (%d)", MAX_OUTPUT_TOKENS_RECOVERY_LIMIT)
        return RecoveryAction.GIVE_UP, messages or []

    # ── 413 prompt_too_long ──
    if error_type == "prompt_too_long":
        # a. collapse_drain（只尝试一次）
        if not state.has_attempted_collapse_drain:
            state.has_attempted_collapse_drain = True
            state.last_recovery_action = RecoveryAction.COLLAPSE_DRAIN
            log.info("尝试 collapse drain")
            return RecoveryAction.COLLAPSE_DRAIN, messages or []

        # b. reactive_compact
        if not state.has_attempted_reactive_compact:
            state.has_attempted_reactive_compact = True
            state.last_recovery_action = RecoveryAction.COMPACT
            log.info("尝试 reactive compact")
            return RecoveryAction.COMPACT, messages or []

        # c. 放弃
        log.warning("413 恢复失败：collapse + compact 都不够")
        return RecoveryAction.GIVE_UP, messages or []

    # ── 模型不可用 ──
    if error_type == "model_unavailable":
        if llm and llm.fallback_model:
            llm.switch_to_fallback()
            if messages:
                messages = llm.strip_thinking_signatures(messages)
            state.last_recovery_action = RecoveryAction.FALLBACK_MODEL
            log.info("切换到 fallback 模型: %s", llm.model_name)
            return RecoveryAction.FALLBACK_MODEL, messages or []
        log.warning("模型不可用且无 fallback")
        return RecoveryAction.GIVE_UP, messages or []

    # ── rate_limit ──
    if error_type == "rate_limit":
        log.info("API rate limit，稍后重试")
        # 实际等待在调用方实现
        return RecoveryAction.RECOVERY_MESSAGE, messages or []

    # ── 未知错误 ──
    log.error("未知错误，无法恢复: %s: %s", type(error).__name__, error)
    return RecoveryAction.GIVE_UP, messages or []
