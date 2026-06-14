"""tools/mcp — MCP (Model Context Protocol) 适配器。

支持连接外部 MCP 服务器，发现工具并注册为 LangChain 工具。
"""

from LangCode.tools.mcp.client import MCPManager, MCPServerConnection

__all__ = ["MCPManager", "MCPServerConnection"]
