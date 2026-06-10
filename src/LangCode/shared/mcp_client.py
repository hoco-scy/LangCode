"""MCP (Model Context Protocol) 客户端集成

支持连接外部 MCP 服务器，发现工具并注册为 LangChain 工具。
配置文件：.langcode/mcp.json

配置格式：
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "description": "文件系统访问工具"
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "xxx"},
      "description": "GitHub 操作工具"
    }
  }
}
"""

import json
import os
import asyncio
from typing import Optional, Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("mcp_client")

# MCP 配置文件路径
MCP_CONFIG_PATH = ".langcode/mcp.json"


def load_mcp_config(config_path: str = MCP_CONFIG_PATH) -> dict:
    """加载 MCP 服务器配置"""
    if not os.path.isfile(config_path):
        log.debug("MCP 配置文件不存在: %s", config_path)
        return {"servers": {}}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        log.info("加载 MCP 配置: %d 个服务器", len(config.get("servers", {})))
        return config
    except Exception as e:
        log.error("加载 MCP 配置失败: %s", e)
        return {"servers": {}}


class MCPServerConnection:
    """单个 MCP 服务器的连接管理"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.command = config["command"]
        self.args = config.get("args", [])
        self.env = config.get("env", {})
        self.description = config.get("description", f"MCP 服务器: {name}")
        self._session = None
        self._tools = []
        self._connected = False

    async def connect(self) -> bool:
        """连接到 MCP 服务器并发现工具"""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            # 准备环境变量
            env = dict(os.environ)
            if self.env:
                env.update(self.env)

            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=env,
            )

            log.info("MCP 连接: %s (%s %s)", self.name, self.command, " ".join(self.args[:3]))

            # 使用 stdio 传输连接
            self._stdio_ctx = stdio_client(server_params)
            read_stream, write_stream = await self._stdio_ctx.__aenter__()

            self._session_ctx = ClientSession(read_stream, write_stream)
            self._session = await self._session_ctx.__aenter__()

            # 初始化
            await self._session.initialize()

            # 发现工具
            tools_result = await self._session.list_tools()
            self._tools = tools_result.tools if hasattr(tools_result, 'tools') else []

            self._connected = True
            log.info("MCP %s: 已连接，发现 %d 个工具", self.name, len(self._tools))
            return True

        except FileNotFoundError:
            log.warning("MCP %s: 命令不存在 '%s'", self.name, self.command)
            return False
        except Exception as e:
            log.error("MCP %s: 连接失败 - %s", self.name, e)
            return False

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP 工具"""
        if not self._connected or not self._session:
            return {"success": False, "error": f"MCP 服务器 '{self.name}' 未连接"}

        try:
            result = await self._session.call_tool(tool_name, arguments)
            # 提取内容
            content_parts = []
            if hasattr(result, 'content'):
                for item in result.content:
                    if hasattr(item, 'text'):
                        content_parts.append(item.text)
                    elif hasattr(item, 'type'):
                        content_parts.append(f"[{item.type} content]")
            content = "\n".join(content_parts) if content_parts else str(result)
            is_error = getattr(result, 'isError', False)
            return {
                "success": not is_error,
                "content": content,
                "error": content if is_error else None,
            }
        except Exception as e:
            log.error("MCP %s: 调用工具 %s 失败 - %s", self.name, tool_name, e)
            return {"success": False, "error": str(e)}

    async def disconnect(self):
        """断开连接"""
        try:
            if hasattr(self, '_session_ctx') and self._session_ctx:
                await self._session_ctx.__aexit__(None, None, None)
            if hasattr(self, '_stdio_ctx') and self._stdio_ctx:
                await self._stdio_ctx.__aexit__(None, None, None)
        except Exception as e:
            log.debug("MCP %s: 断开连接时出错 - %s", self.name, e)
        finally:
            self._connected = False
            self._session = None

    def get_tools_info(self) -> list[dict]:
        """获取工具信息列表"""
        tools = []
        for t in self._tools:
            tools.append({
                "name": t.name,
                "description": t.description or f"MCP 工具: {t.name}",
                "input_schema": t.inputSchema if hasattr(t, 'inputSchema') else {},
            })
        return tools

    @property
    def is_connected(self) -> bool:
        return self._connected


def _run_async(coro):
    """在同步上下文中运行异步代码"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果已有事件循环在运行（如 Jupyter），使用 nest_asyncio
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class MCPManager:
    """MCP 服务器管理器"""

    def __init__(self):
        self.connections: dict[str, MCPServerConnection] = {}

    def connect_all(self, config_path: str = MCP_CONFIG_PATH) -> dict:
        """连接所有配置的 MCP 服务器"""
        config = load_mcp_config(config_path)
        servers = config.get("servers", {})
        if not servers:
            return {"connected": 0, "total": 0, "message": "无 MCP 服务器配置"}

        connected = 0
        results = {}

        async def _connect_all():
            nonlocal connected
            for name, server_config in servers.items():
                conn = MCPServerConnection(name, server_config)
                success = await conn.connect()
                if success:
                    self.connections[name] = conn
                    connected += 1
                    results[name] = {"status": "connected", "tools": len(conn._tools)}
                else:
                    results[name] = {"status": "failed"}

        _run_async(_connect_all())

        log.info("MCP 初始化完成: %d/%d 服务器已连接", connected, len(servers))
        return {
            "connected": connected,
            "total": len(servers),
            "servers": results,
        }

    def create_langchain_tools(self) -> list:
        """为所有已连接的 MCP 服务器创建 LangChain 工具"""
        lc_tools = []

        for name, conn in self.connections.items():
            if not conn.is_connected:
                continue

            for mcp_tool in conn.get_tools_info():
                lc_tool = self._make_langchain_tool(name, mcp_tool)
                lc_tools.append(lc_tool)

        log.info("创建 %d 个 MCP LangChain 工具", len(lc_tools))
        return lc_tools

    def _make_langchain_tool(self, server_name: str, tool_info: dict):
        """将单个 MCP 工具转为 LangChain 工具"""
        tool_name = f"mcp_{server_name}_{tool_info['name']}"
        tool_desc = tool_info["description"]
        input_schema = tool_info.get("input_schema", {})
        conn = self.connections[server_name]

        # 从 input schema 提取参数信息
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        # 构建 Pydantic 输入模型的字段
        fields = {}
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get("type", "string")
            desc = prop_info.get("description", "")
            py_type = str  # 默认为字符串
            if prop_type == "integer":
                py_type = int
            elif prop_type == "number":
                py_type = float
            elif prop_type == "boolean":
                py_type = bool

            if prop_name in required:
                fields[prop_name] = (py_type, Field(description=desc))
            else:
                fields[prop_name] = (Optional[py_type], Field(default=None, description=desc))

        # 动态创建 Pydantic 输入模型
        if fields:
            InputModel = type(f"{tool_name}_input", (BaseModel,), {
                '__annotations__': {k: v[0] for k, v in fields.items()},
                **{k: v[1] for k, v in fields.items()},
            })
        else:
            InputModel = BaseModel

        # 创建工具函数
        mcp_tool_name = tool_info['name']
        full_desc = f"[MCP:{server_name}] {tool_desc}"

        def _make_caller(tname, c, desc):
            def caller(**kwargs):
                """MCP tool wrapper"""
                args = {k: v for k, v in kwargs.items() if v is not None}
                return _run_async(c.call_tool(tname, args))
            caller.__doc__ = desc
            caller.__name__ = f"mcp_{server_name}_{tname}"
            return caller

        caller_fn = _make_caller(mcp_tool_name, conn, full_desc)

        langchain_tool = tool(
            tool_name,
            args_schema=InputModel,
            return_direct=False,
        )(caller_fn)

        return langchain_tool

    def disconnect_all(self):
        """断开所有连接"""
        async def _disconnect_all():
            for conn in self.connections.values():
                await conn.disconnect()
        _run_async(_disconnect_all())
        self.connections.clear()
