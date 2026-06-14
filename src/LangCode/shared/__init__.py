"""shared — 共享内核（v2 最小化设计）

v2 变更：仅保留零业务逻辑的模块：
- state: LCState TypedDict 定义（图流程状态）
- models: 工具响应的 Pydantic 模型
- errors: 异常类型层次
- logger: 日志工厂

已迁移到其他模块的（不再在此处导入）：
- config → services/config.py
- llm → services/llm.py
- tools → tools/builtin/（逐步迁移中）
- ast_tools → tools/ast/（逐步迁移中）
- delegate_tools → agents/router.py (tool calling)
- plan_tools → planning/planner.py
- mode_tools → permissions/model.py
- routing → agents/router.py
- prompts → agents/prompts.py
- context → engine/context.py
- session → state/session.py (Transcript)
- mcp_client → tools/mcp/ (逐步迁移中)
"""

from LangCode.shared.state import LCState
from LangCode.shared.schemas import (
    ToolResponse, FileContentResponse, WriteResponse, EditResponse,
    SearchResponse, CommandResponse, PythonResponse, FetchAPIResponse,
    GitStatusResponse, GitDiffResponse, GitLogResponse, GitBlameResponse,
    GitCommitInfo, GitBlameEntry,
)
from LangCode.shared.logger import get_logger
from LangCode.shared.session import SessionStore
from LangCode.shared.tools import all_tools
from LangCode.shared.ast_tools import ast_tools
from LangCode.shared.mcp_client import MCPManager, MCPServerConnection

__all__ = [
    "LCState",
    "ToolResponse", "FileContentResponse", "WriteResponse", "EditResponse",
    "SearchResponse", "CommandResponse", "PythonResponse", "FetchAPIResponse",
    "GitStatusResponse", "GitDiffResponse", "GitLogResponse", "GitBlameResponse",
    "GitCommitInfo", "GitBlameEntry",
    "get_logger",
    "SessionStore",
    "all_tools",
    "ast_tools",
    "MCPManager", "MCPServerConnection",
]
