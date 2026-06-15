"""shared.errors 异常层次测试"""

import pytest
from LangCode.shared.errors import (
    LangCodeError,
    ToolExecutionError,
    PermissionDeniedError,
    ContextOverflowError,
    APIRateLimitError,
    ModelUnavailableError,
    ConfigLoadError,
    CircuitBreakerOpen,
)


class TestLangCodeError:
    def test_base_defaults(self):
        e = LangCodeError("test")
        assert str(e) == "test"
        assert e.recoverable is False
        assert e.retry_after_ms == 0

    def test_base_with_recoverable(self):
        e = LangCodeError("retry", recoverable=True, retry_after_ms=5000)
        assert e.recoverable is True
        assert e.retry_after_ms == 5000

    def test_hierarchy(self):
        """所有异常类型都是 LangCodeError 的子类"""
        for cls in [ToolExecutionError, PermissionDeniedError, ContextOverflowError,
                     APIRateLimitError, ModelUnavailableError, ConfigLoadError,
                     CircuitBreakerOpen]:
            assert issubclass(cls, LangCodeError)


class TestToolExecutionError:
    def test_basic(self):
        e = ToolExecutionError("my_tool", "failed to execute")
        assert e.tool_name == "my_tool"
        assert "failed to execute" in str(e)

    def test_recoverable(self):
        e = ToolExecutionError("shell", "timeout", recoverable=True)
        assert e.recoverable is True


class TestPermissionDeniedError:
    def test_fields(self):
        e = PermissionDeniedError("write_file", "plan", "plan 模式禁止写操作")
        assert e.tool_name == "write_file"
        assert e.mode == "plan"
        assert "plan" in str(e).lower()

    def test_not_recoverable(self):
        e = PermissionDeniedError("bash", "default", "no rule matched")
        assert e.recoverable is False


class TestContextOverflowError:
    def test_fields(self):
        e = ContextOverflowError(100_000, 80_000)
        assert e.token_count == 100_000
        assert e.max_tokens == 80_000
        assert e.recoverable is True

    def test_message_contains_numbers(self):
        e = ContextOverflowError(90_000, 80_000)
        assert "90000" in str(e) or "90,000" in str(e)


class TestAPIRateLimitError:
    def test_defaults(self):
        e = APIRateLimitError()
        assert e.recoverable is True
        assert e.retry_after_ms == 1000

    def test_custom_retry(self):
        e = APIRateLimitError(retry_after_ms=30_000)
        assert e.retry_after_ms == 30_000


class TestModelUnavailableError:
    def test_fields(self):
        e = ModelUnavailableError("gpt-4", "model overloaded")
        assert e.model_name == "gpt-4"
        assert e.recoverable is True

    def test_default_message(self):
        e = ModelUnavailableError("mimo-v2.5-pro")
        assert "mimo-v2.5-pro" in str(e)


class TestCircuitBreakerOpen:
    def test_fields(self):
        e = CircuitBreakerOpen("auto_compact", 3)
        assert e.operation == "auto_compact"
        assert e.consecutive_failures == 3
        assert e.recoverable is True
        assert e.retry_after_ms == 30_000
