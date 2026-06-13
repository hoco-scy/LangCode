"""shared/mode_tools.py — 权限模式工具过滤测试"""

from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage

from LangCode.shared.mode_tools import (
    PLAN_MODE_TOOLS, filter_tools_for_mode, ModeAwareToolNode,
)


# 创建真实的 LangChain 工具用于测试
@tool("read_file")
def read_file(file_path: str) -> str:
    """读取文件内容"""
    return "file content"


@tool("write_file")
def write_file(file_path: str, content: str) -> str:
    """写入文件"""
    return "written"


@tool("search_files")
def search_files(pattern: str) -> str:
    """搜索文件"""
    return "results"


@tool("edit_file")
def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """编辑文件"""
    return "edited"


ALL_TEST_TOOLS = [read_file, write_file, search_files, edit_file]


class TestPlanModeTools:
    def test_includes_read_tools(self):
        assert "read_file" in PLAN_MODE_TOOLS
        assert "search_files" in PLAN_MODE_TOOLS
        assert "fetch_api" in PLAN_MODE_TOOLS

    def test_includes_memory_tools(self):
        assert "memory_search" in PLAN_MODE_TOOLS
        assert "memory_list" in PLAN_MODE_TOOLS

    def test_excludes_write_tools(self):
        assert "write_file" not in PLAN_MODE_TOOLS
        assert "edit_file" not in PLAN_MODE_TOOLS

    def test_excludes_execution_tools(self):
        assert "execute_shell" not in PLAN_MODE_TOOLS
        assert "run_python" not in PLAN_MODE_TOOLS


class TestFilterToolsForMode:
    def test_build_mode_returns_all(self):
        result = filter_tools_for_mode(ALL_TEST_TOOLS, "build")
        assert len(result) == 4

    def test_plan_mode_filters_write_tools(self):
        result = filter_tools_for_mode(ALL_TEST_TOOLS, "plan")
        assert len(result) == 2
        assert all(t.name in PLAN_MODE_TOOLS for t in result)

    def test_plan_mode_empty_result(self):
        result = filter_tools_for_mode([write_file, edit_file], "plan")
        assert len(result) == 0


class TestModeAwareToolNode:
    def test_node_creation_with_real_tools(self):
        node = ModeAwareToolNode(tools=ALL_TEST_TOOLS)
        assert len(node._all_tools) == 4

    def test_plan_mode_filters_in_filter_tool_calls(self):
        node = ModeAwareToolNode(tools=ALL_TEST_TOOLS)
        state = {"agent_mode": "plan"}
        tool_calls = [
            {"name": "read_file", "args": {"file_path": "test.py"}, "id": "tc1"},
            {"name": "write_file", "args": {"file_path": "test.py", "content": "x"}, "id": "tc2"},
        ]
        allowed, denied = node._filter_tool_calls(state, tool_calls)
        assert len(allowed) == 1
        assert allowed[0]["name"] == "read_file"
        assert len(denied) == 1
        assert denied[0]["name"] == "write_file"

    def test_build_mode_no_filtering(self):
        node = ModeAwareToolNode(tools=ALL_TEST_TOOLS)
        state = {"agent_mode": "build"}
        tool_calls = [
            {"name": "read_file", "args": {}, "id": "tc1"},
            {"name": "write_file", "args": {}, "id": "tc2"},
        ]
        allowed, denied = node._filter_tool_calls(state, tool_calls)
        assert len(allowed) == 2
        assert len(denied) == 0

    def test_all_denied_in_plan_mode(self):
        node = ModeAwareToolNode(tools=[write_file, edit_file])
        state = {"agent_mode": "plan"}
        tool_calls = [
            {"name": "write_file", "args": {}, "id": "tc1"},
            {"name": "edit_file", "args": {}, "id": "tc2"},
        ]
        allowed, denied = node._filter_tool_calls(state, tool_calls)
        assert len(allowed) == 0
        assert len(denied) == 2

    def test_mixed_allowed_and_denied(self):
        node = ModeAwareToolNode(tools=ALL_TEST_TOOLS)
        state = {"agent_mode": "plan"}
        tool_calls = [
            {"name": "read_file", "args": {"file_path": "a.py"}, "id": "tc1"},
            {"name": "search_files", "args": {"pattern": "*.py"}, "id": "tc2"},
            {"name": "write_file", "args": {"file_path": "b.py", "content": "x"}, "id": "tc3"},
            {"name": "edit_file", "args": {"file_path": "c.py"}, "id": "tc4"},
        ]
        allowed, denied = node._filter_tool_calls(state, tool_calls)
        assert len(allowed) == 2
        assert len(denied) == 2
