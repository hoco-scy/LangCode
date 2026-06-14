"""shared — 共享内核（v2 最小化设计）

仅保留零业务逻辑的模块：
- types: LCState TypedDict 定义（图流程状态）
- models: 工具响应的 Pydantic 模型
- errors: 异常类型层次
- logger: 日志工厂
"""

from LangCode.shared.types import LCState
from LangCode.shared.models import (
    ToolResponse, FileContentResponse, WriteResponse, EditResponse,
    SearchResponse, CommandResponse, PythonResponse, FetchAPIResponse,
    GitStatusResponse, GitDiffResponse, GitLogResponse, GitBlameResponse,
    GitCommitInfo, GitBlameEntry,
)
from LangCode.shared.logger import get_logger
from LangCode.shared.errors import (
    LangCodeError, ToolExecutionError, PermissionDeniedError,
    ContextOverflowError, APIRateLimitError, ModelUnavailableError,
    ConfigLoadError, CircuitBreakerOpen,
)

__all__ = [
    "LCState",
    "ToolResponse", "FileContentResponse", "WriteResponse", "EditResponse",
    "SearchResponse", "CommandResponse", "PythonResponse", "FetchAPIResponse",
    "GitStatusResponse", "GitDiffResponse", "GitLogResponse", "GitBlameResponse",
    "GitCommitInfo", "GitBlameEntry",
    "get_logger",
    "LangCodeError", "ToolExecutionError", "PermissionDeniedError",
    "ContextOverflowError", "APIRateLimitError", "ModelUnavailableError",
    "ConfigLoadError", "CircuitBreakerOpen",
]
