"""LangCode 异常层次

参考 Claude Code 错误类型设计：
- LangCodeError 为所有异常的基类
- recoverable 标记指示是否可恢复（影响错误恢复链决策）
- retry_after_ms 指示重试间隔（用于 rate limit 等场景）
"""

from typing import Optional


class LangCodeError(Exception):
    """所有 LangCode 异常的基类"""
    def __init__(self, message: str, *,
                 recoverable: bool = False,
                 retry_after_ms: int = 0):
        super().__init__(message)
        self.recoverable = recoverable
        self.retry_after_ms = retry_after_ms


class ToolExecutionError(LangCodeError):
    """工具执行失败"""
    def __init__(self, tool_name: str, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.tool_name = tool_name


class PermissionDeniedError(LangCodeError):
    """权限检查拒绝"""
    def __init__(self, tool_name: str, mode: str, reason: str):
        super().__init__(
            f"Permission denied: {tool_name} (mode={mode}): {reason}",
            recoverable=False,
        )
        self.tool_name = tool_name
        self.mode = mode
        self.reason = reason


class ContextOverflowError(LangCodeError):
    """上下文窗口溢出"""
    def __init__(self, token_count: int, max_tokens: int):
        super().__init__(
            f"Context overflow: {token_count} tokens > {max_tokens} max",
            recoverable=True,
        )
        self.token_count = token_count
        self.max_tokens = max_tokens


class APIRateLimitError(LangCodeError):
    """API 速率限制"""
    def __init__(self, message: str = "", retry_after_ms: int = 1000):
        super().__init__(
            message or "API rate limit exceeded",
            recoverable=True,
            retry_after_ms=retry_after_ms,
        )


class ModelUnavailableError(LangCodeError):
    """模型不可用"""
    def __init__(self, model_name: str, message: str = ""):
        super().__init__(
            message or f"Model unavailable: {model_name}",
            recoverable=True,
        )
        self.model_name = model_name


class ConfigLoadError(LangCodeError):
    """配置加载失败"""
    def __init__(self, path: str, message: str = ""):
        super().__init__(
            message or f"Failed to load config: {path}",
            recoverable=False,
        )
        self.path = path


class CircuitBreakerOpen(LangCodeError):
    """断路器已打开（连续失败次数超限）"""
    def __init__(self, operation: str, consecutive_failures: int):
        super().__init__(
            f"Circuit breaker open for {operation} "
            f"after {consecutive_failures} consecutive failures",
            recoverable=True,
            retry_after_ms=30_000,
        )
        self.operation = operation
        self.consecutive_failures = consecutive_failures
