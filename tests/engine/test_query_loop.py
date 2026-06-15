"""engine.query_loop — 查询循环状态机测试"""

import pytest

from LangCode.engine.query_loop import (
    LoopState, LoopResult, TerminalReason, ContinueReason,
    check_max_turns, update_usage,
)


class TestTerminalReason:
    def test_values(self):
        expected = {"completed", "max_turns", "token_budget",
                    "aborted_streaming", "aborted_tools",
                    "prompt_too_long", "model_error"}
        actual = {e.value for e in TerminalReason}
        assert actual == expected

    def test_string_enum(self):
        assert TerminalReason.COMPLETED == "completed"
        assert TerminalReason.MAX_TURNS == "max_turns"
        assert TerminalReason("completed") is TerminalReason.COMPLETED


class TestContinueReason:
    def test_values(self):
        expected = {"next_turn", "auto_compact_retry", "max_output_escalate",
                    "max_output_recovery", "fallback_model",
                    "token_budget_continuation"}
        actual = {e.value for e in ContinueReason}
        assert actual == expected

    def test_string_enum(self):
        assert ContinueReason.NEXT_TURN == "next_turn"
        assert ContinueReason("auto_compact_retry") is ContinueReason.AUTO_COMPACT_RETRY


class TestLoopState:
    def test_defaults(self):
        state = LoopState()
        assert state.turn_count == 0
        assert state.total_usage == {"input_tokens": 0, "output_tokens": 0}
        assert state.transition is None
        assert state.terminal_reason is None
        assert state.max_output_tokens_override is None
        assert state.max_output_recovery_count == 0
        assert state.has_attempted_reactive_compact is False
        assert state.has_attempted_collapse_drain is False

    def test_custom_values(self):
        state = LoopState(
            turn_count=5,
            transition=ContinueReason.NEXT_TURN,
            max_output_tokens_override=64000,
        )
        assert state.turn_count == 5
        assert state.transition == ContinueReason.NEXT_TURN
        assert state.max_output_tokens_override == 64000


class TestLoopResult:
    def test_create(self):
        result = LoopResult(
            terminal_reason=TerminalReason.COMPLETED,
            turn_count=3,
            total_usage={"input_tokens": 100, "output_tokens": 50},
        )
        assert result.terminal_reason == TerminalReason.COMPLETED
        assert result.turn_count == 3
        assert result.error is None

    def test_with_error(self):
        result = LoopResult(
            terminal_reason=TerminalReason.MODEL_ERROR,
            turn_count=1,
            total_usage={},
            error="API timeout",
        )
        assert result.error == "API timeout"


class TestCheckMaxTurns:
    def test_under_limit(self):
        state = LoopState(turn_count=5)
        assert check_max_turns(state, 50) is False

    def test_at_limit(self):
        state = LoopState(turn_count=50)
        assert check_max_turns(state, 50) is True

    def test_over_limit(self):
        state = LoopState(turn_count=51)
        assert check_max_turns(state, 50) is True

    def test_zero_max(self):
        state = LoopState(turn_count=0)
        assert check_max_turns(state, 0) is True


class TestUpdateUsage:
    def test_basic(self):
        state = LoopState()
        update_usage(state, {"input_tokens": 100, "output_tokens": 50})
        assert state.total_usage["input_tokens"] == 100
        assert state.total_usage["output_tokens"] == 50

    def test_accumulates(self):
        state = LoopState()
        update_usage(state, {"input_tokens": 100, "output_tokens": 50})
        update_usage(state, {"input_tokens": 200, "output_tokens": 80})
        assert state.total_usage["input_tokens"] == 300
        assert state.total_usage["output_tokens"] == 130

    def test_missing_keys(self):
        state = LoopState()
        update_usage(state, {"input_tokens": 100})
        assert state.total_usage["input_tokens"] == 100
        assert state.total_usage["output_tokens"] == 0

    def test_empty_usage(self):
        state = LoopState()
        update_usage(state, {})
        assert state.total_usage["input_tokens"] == 0
