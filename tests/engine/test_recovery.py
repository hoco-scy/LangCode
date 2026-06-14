"""engine.recovery — 错误恢复链测试"""

import pytest
from LangCode.engine.recovery import (
    RecoveryState, RecoveryAction,
    classify_error, try_recover,
    MAX_OUTPUT_TOKENS_RECOVERY_LIMIT, ESCALATED_MAX_TOKENS,
)


class TestClassifyError:
    def test_max_output(self):
        assert classify_error(Exception("max_output_tokens exceeded")) == "max_output"

    def test_prompt_too_long(self):
        assert classify_error(Exception("413 request too long")) == "prompt_too_long"

    def test_model_unavailable(self):
        assert classify_error(Exception("model overloaded")) == "model_unavailable"

    def test_rate_limit(self):
        assert classify_error(Exception("429 rate limit")) == "rate_limit"

    def test_unknown(self):
        assert classify_error(Exception("something else")) == "unknown"


class TestMaxOutputRecovery:
    def test_first_escalates(self):
        state = RecoveryState()
        action, msgs = try_recover(state, Exception("max_output_tokens exceeded"))
        assert action == RecoveryAction.ESCALATE
        assert state.max_output_tokens_override == ESCALATED_MAX_TOKENS

    def test_then_recovery_message(self):
        state = RecoveryState(max_output_tokens_override=ESCALATED_MAX_TOKENS)
        action, msgs = try_recover(
            state, Exception("max_output_tokens exceeded"),
            messages=["existing"],
        )
        assert action == RecoveryAction.RECOVERY_MESSAGE
        assert len(msgs) == 2
        assert state.max_output_recovery_count == 1

    def test_gives_up_after_max_recoveries(self):
        state = RecoveryState(
            max_output_tokens_override=ESCALATED_MAX_TOKENS,
            max_output_recovery_count=MAX_OUTPUT_TOKENS_RECOVERY_LIMIT,
        )
        action, msgs = try_recover(state, Exception("max_output_tokens exceeded"))
        assert action == RecoveryAction.GIVE_UP


class TestPromptTooLongRecovery:
    def test_first_collapse_drain(self):
        state = RecoveryState()
        action, msgs = try_recover(state, Exception("413 request too long"))
        assert action == RecoveryAction.COLLAPSE_DRAIN
        assert state.has_attempted_collapse_drain is True

    def test_then_compact(self):
        state = RecoveryState(has_attempted_collapse_drain=True)
        action, msgs = try_recover(state, Exception("413 request too long"))
        assert action == RecoveryAction.COMPACT
        assert state.has_attempted_reactive_compact is True

    def test_gives_up_after_both_fail(self):
        state = RecoveryState(
            has_attempted_collapse_drain=True,
            has_attempted_reactive_compact=True,
        )
        action, msgs = try_recover(state, Exception("413 request too long"))
        assert action == RecoveryAction.GIVE_UP


class TestModelUnavailableRecovery:
    def test_switches_to_fallback(self):
        mock_llm = type("LLM", (), {
            "fallback_model": True,
            "model_name": "test",
            "switch_to_fallback": lambda self: None,
            "strip_thinking_signatures": lambda self, msgs: msgs,
        })()
        state = RecoveryState()
        action, msgs = try_recover(
            state, Exception("model overloaded"),
            llm=mock_llm, messages=["test"],
        )
        assert action == RecoveryAction.FALLBACK_MODEL

    def test_gives_up_without_fallback(self):
        mock_llm = type("LLM", (), {"fallback_model": None})()
        state = RecoveryState()
        action, msgs = try_recover(
            state, Exception("model unavailable"),
            llm=mock_llm,
        )
        assert action == RecoveryAction.GIVE_UP


class TestStatePersistence:
    def test_state_persists_across_calls(self):
        state = RecoveryState()
        try_recover(state, Exception("413 request too long"))
        assert state.has_attempted_collapse_drain is True
        try_recover(state, Exception("413 request too long"))
        assert state.has_attempted_reactive_compact is True
