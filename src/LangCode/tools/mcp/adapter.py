"""MCP Tool → LangChain BaseTool 适配器。

v2.1 变更：不再继承 Tool ABC，直接返回 LangChain BaseTool。
MCP 工具包装为 @tool 装饰器函数，与 builtin 工具保持一致。
"""

from __future__ import annotations

from typing import Optional, Any

from langchain.tools import tool as langchain_tool
from pydantic import BaseModel, Field, create_model

from LangCode.tools.mcp.client import MCPServerConnection
from LangCode.shared.logger import get_logger

log = get_logger("tools.mcp.adapter")


def _json_type_to_python(json_type: str) -> type:
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }
    return mapping.get(json_type, str)


def _build_input_model(tool_name: str, input_schema: dict) -> type[BaseModel]:
    """从 MCP JSON Schema 动态构建 Pydantic 模型。"""
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    fields = {}
    for prop_name, prop_info in properties.items():
        py_type = _json_type_to_python(prop_info.get("type", "string"))
        desc = prop_info.get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(description=desc))
        else:
            fields[prop_name] = (Optional[py_type], Field(default=None, description=desc))

    if not fields:
        return type(f"MCP_{tool_name}_Input", (BaseModel,), {})

    return create_model(f"MCP_{tool_name}_Input", **fields)


def create_mcp_tools(connection: MCPServerConnection) -> list:
    """为单个 MCP 连接创建 LangChain BaseTool 列表。"""
    tools = []
    for info in connection.get_tools_info():
        lc_tool = _build_mcp_tool(
            server_name=connection.name,
            tool_name=info["name"],
            tool_description=info.get("description", ""),
            input_schema=info.get("input_schema", {}),
            connection=connection,
        )
        tools.append(lc_tool)
    return tools


def _build_mcp_tool(
    server_name: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    connection: MCPServerConnection,
):
    """构建单个 MCP LangChain BaseTool。"""
    full_name = f"mcp_{server_name}_{tool_name}"
    description = f"[MCP:{server_name}] {tool_description}"
    input_model = _build_input_model(tool_name, input_schema)

    import asyncio

    async def _mcp_invoke(**kwargs) -> str:
        arguments = {k: v for k, v in kwargs.items() if v is not None}
        log.debug("MCP 调用: %s.%s(%s)", server_name, tool_name, arguments)
        result = await connection.call_tool(tool_name, arguments)
        if result.get("success"):
            return result.get("content", "")
        return f"[MCP 错误] {result.get('error', '未知错误')}"

    _mcp_invoke.__name__ = full_name
    _mcp_invoke.__doc__ = description

    return langchain_tool(full_name, args_schema=input_model)(_mcp_invoke)
