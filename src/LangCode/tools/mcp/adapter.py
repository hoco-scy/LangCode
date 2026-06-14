"""MCP Tool → LangCode Tool 适配器。

将 MCP 服务器发现的工具包装为 LangCode Tool<I,O> 接口，
使其可以注册到 ToolRegistry，走统一的权限检查和并发调度。

参考 Claude Code mcp/adapter.ts。
"""

from __future__ import annotations

import asyncio
from typing import Optional, Any

from pydantic import BaseModel, Field, create_model

from LangCode.tools.base import Tool, ToolResult
from LangCode.tools.mcp.client import MCPServerConnection
from LangCode.shared.logger import get_logger

log = get_logger("tools.mcp.adapter")


def _json_type_to_python(json_type: str) -> type:
    """JSON Schema type → Python type"""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }
    return mapping.get(json_type, str)


def _build_input_model(
    tool_name: str, input_schema: dict
) -> type[BaseModel]:
    """从 MCP 工具的 JSON Schema 动态构建 Pydantic 模型。"""
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
        # 无参数的工具也需要一个空的 input model
        return type(f"MCP_{tool_name}_Input", (BaseModel,), {})

    return create_model(f"MCP_{tool_name}_Input", **fields)


class MCPToolAdapter(Tool[BaseModel, str]):
    """将单个 MCP 工具适配为 LangCode Tool 接口。

    特性:
    - 动态生成 input_schema（从 MCP JSON Schema）
    - 异步调用 MCP 服务器
    - 标记为非并发安全（网络调用）
    - 标记为非只读（MCP 工具可能有副作用）
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        connection: MCPServerConnection,
    ):
        self._server_name = server_name
        self._connection = connection
        self.name = f"mcp_{server_name}_{tool_name}"
        self.description = f"[MCP:{server_name}] {tool_description}"
        self.input_schema = _build_input_model(tool_name, input_schema)

    async def call(self, args: BaseModel, context) -> ToolResult[str]:
        arguments = {k: v for k, v in args.model_dump().items() if v is not None}
        log.debug("MCP 调用: %s.%s(%s)", self._server_name, self.name, arguments)

        result = await self._connection.call_tool(
            self.name.removeprefix(f"mcp_{self._server_name}_"),
            arguments,
        )

        if result.get("success"):
            return ToolResult(data=result.get("content", ""))
        else:
            return ToolResult(data=f"[MCP 错误] {result.get('error', '未知错误')}")

    def check_permissions(self, args, context):
        from LangCode.permissions.model import PermissionResult
        return PermissionResult.ask(f"MCP 工具需要确认: {self.name}")

    def is_concurrency_safe(self, args) -> bool:
        return False  # 网络调用，不安全

    def is_read_only(self, args) -> bool:
        return False  # MCP 工具可能有副作用


def create_mcp_tools(
    connection: MCPServerConnection,
) -> list[MCPToolAdapter]:
    """为单个 MCP 连接创建所有工具适配器。"""
    tools = []
    for info in connection.get_tools_info():
        adapter = MCPToolAdapter(
            server_name=connection.name,
            tool_name=info["name"],
            tool_description=info.get("description", ""),
            input_schema=info.get("input_schema", {}),
            connection=connection,
        )
        tools.append(adapter)
    return tools
