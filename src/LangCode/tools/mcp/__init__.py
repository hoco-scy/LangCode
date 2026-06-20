"""tools/mcp — MCP (Model Context Protocol) 适配器。

支持连接外部 MCP 服务器，发现工具并注册为 LangChain BaseTool。
"""

from LangCode.tools.mcp.client import MCPManager, MCPServerConnection
from LangCode.tools.mcp.adapter import create_mcp_tools

__all__ = [
    "MCPManager", "MCPServerConnection",
    "create_mcp_tools",
]
