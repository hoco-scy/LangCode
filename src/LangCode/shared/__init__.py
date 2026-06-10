"""shared — 共享基础设施

所有模块依赖的公共组件：
- state: LCState TypedDict 定义
- schemas: 工具响应的 Pydantic 模型
- tools: 11 个通用工具（文件读写、Shell/Python 执行、Git 操作）
- ast_tools: 6 个 AST 结构化编辑工具
- ast_editor: tree-sitter AST 编辑引擎
- llm: LLM 初始化
- config: 环境变量配置
- logger: 日志
- prompts: 平台提示
- context: 上下文窗口管理（token 计数 + 裁剪 + 摘要）
- routing: 共享条件边函数
- command: 对话命令常量
- mcp_client: MCP 协议客户端
"""

from LangCode.shared.state import LCState
from LangCode.shared.schemas import (
    ToolResponse, FileContentResponse, WriteResponse, EditResponse,
    SearchResponse, CommandResponse, PythonResponse, FetchAPIResponse,
    GitStatusResponse, GitDiffResponse, GitLogResponse, GitBlameResponse,
    GitCommitInfo, GitBlameEntry,
)
from LangCode.shared.tools import all_tools
from LangCode.shared.ast_tools import ast_tools
from LangCode.shared.llm import llm
from LangCode.shared.config import LC_MODEL_NAME, LC_API_KEY, LC_BASE_URL
from LangCode.shared.logger import get_logger
from LangCode.shared.prompts import get_platform_prompt
from LangCode.shared.command import COMMAND_EXIT, COMMAND_MEMORY
from LangCode.shared.context import (
    count_messages_tokens, trim_messages, summarize_old_messages,
    estimate_tokens, count_message_tokens,
)
from LangCode.shared.routing import should_use_tools
from LangCode.shared.mcp_client import MCPManager, MCPServerConnection

__all__ = [
    # state
    "LCState",
    # schemas
    "ToolResponse", "FileContentResponse", "WriteResponse", "EditResponse",
    "SearchResponse", "CommandResponse", "PythonResponse", "FetchAPIResponse",
    "GitStatusResponse", "GitDiffResponse", "GitLogResponse", "GitBlameResponse",
    "GitCommitInfo", "GitBlameEntry",
    # tools
    "all_tools",
    "ast_tools",
    # llm & config
    "llm",
    "LC_MODEL_NAME", "LC_API_KEY", "LC_BASE_URL",
    # logger
    "get_logger",
    # prompts
    "get_platform_prompt",
    # command
    "COMMAND_EXIT", "COMMAND_MEMORY",
    # context
    "count_messages_tokens", "trim_messages", "summarize_old_messages",
    "estimate_tokens", "count_message_tokens",
    # routing
    "should_use_tools",
    # mcp
    "MCPManager", "MCPServerConnection",
]
