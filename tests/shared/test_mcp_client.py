"""shared/mcp_client.py — MCP 客户端测试（mock MCP 服务器）"""

import asyncio
import json
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from LangCode.shared.mcp_client import load_mcp_config, MCPManager, MCPServerConnection


class TestLoadMcpConfig:
    def test_no_config_file(self, tmp_path):
        config = load_mcp_config(str(tmp_path / "nonexistent.json"))
        assert config == {"servers": {}}

    def test_valid_config(self, tmp_path):
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps({
            "servers": {
                "test": {
                    "command": "echo",
                    "args": ["hello"],
                    "description": "测试服务器"
                }
            }
        }), encoding="utf-8")
        config = load_mcp_config(str(config_file))
        assert "test" in config["servers"]
        assert config["servers"]["test"]["command"] == "echo"

    def test_invalid_json(self, tmp_path):
        config_file = tmp_path / "mcp.json"
        config_file.write_text("not json", encoding="utf-8")
        config = load_mcp_config(str(config_file))
        assert config == {"servers": {}}


class TestMCPServerConnection:
    def test_init(self):
        conn = MCPServerConnection("test", {
            "command": "echo",
            "args": ["hello"],
            "description": "Test"
        })
        assert conn.name == "test"
        assert conn.command == "echo"
        assert conn.is_connected is False

    def test_get_tools_info_empty(self):
        conn = MCPServerConnection("test", {"command": "echo"})
        assert conn.get_tools_info() == []

    def test_call_tool_not_connected(self):
        conn = MCPServerConnection("test", {"command": "echo"})
        result = asyncio.run(conn.call_tool("test_tool", {}))
        assert result["success"] is False
        assert "未连接" in result["error"]

    def test_connect_command_not_found(self):
        conn = MCPServerConnection("test", {
            "command": "nonexistent_command_xyz_12345",
            "args": [],
        })
        result = asyncio.run(conn.connect())
        assert result is False
        assert conn.is_connected is False


class TestMCPManager:
    def test_init(self):
        manager = MCPManager()
        assert len(manager.connections) == 0

    def test_connect_all_no_config(self, tmp_path):
        manager = MCPManager()
        result = manager.connect_all(str(tmp_path / "nonexistent.json"))
        assert result["connected"] == 0
        assert result["total"] == 0

    def test_create_langchain_tools_empty(self):
        manager = MCPManager()
        tools = manager.create_langchain_tools()
        assert tools == []

    def test_create_langchain_tools_with_mock(self):
        manager = MCPManager()
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.get_tools_info.return_value = [
            {
                "name": "read_file",
                "description": "读取文件内容",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                    },
                    "required": ["path"],
                },
            }
        ]
        mock_conn.call_tool = AsyncMock(return_value={
            "success": True, "content": "file content"
        })

        manager.connections["fs"] = mock_conn
        tools = manager.create_langchain_tools()
        assert len(tools) == 1
        assert tools[0].name == "mcp_fs_read_file"

    def test_connect_all_with_bad_command(self, tmp_path):
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps({
            "servers": {
                "bad": {
                    "command": "nonexistent_cmd_12345",
                    "args": [],
                }
            }
        }), encoding="utf-8")
        manager = MCPManager()
        result = manager.connect_all(str(config_file))
        assert result["connected"] == 0
        assert result["total"] == 1
        assert result["servers"]["bad"]["status"] == "failed"
