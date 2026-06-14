"""tools/mcp — MCP (Model Context Protocol) 适配器。

支持连接外部 MCP 服务器，发现工具并注册为 LangCode Tool 接口。
"""

from LangCode.tools.mcp.client import MCPManager, MCPServerConnection
from LangCode.tools.mcp.adapter import MCPToolAdapter, create_mcp_tools

__all__ = [
    "MCPManager", "MCPServerConnection",
    "MCPToolAdapter", "create_mcp_tools",
]
