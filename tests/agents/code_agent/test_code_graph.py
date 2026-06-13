"""agents/code_agent/graph.py — 纯函数测试"""

from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.constants import END

from LangCode.agents.code_agent.graph import (
    _extract_modified_python_files,
    _find_test_files,
    _verify_routing,
)


class TestExtractModifiedPythonFiles:
    def test_extracts_from_write_file(self):
        tc = {"name": "write_file", "args": {"file_path": "/tmp/test.py"}, "id": "tc1"}
        msg = AIMessage(content="", tool_calls=[tc])
        state = {"messages": [HumanMessage(content="hi"), msg]}
        assert _extract_modified_python_files(state) == ["/tmp/test.py"]

    def test_extracts_from_edit_file(self):
        tc = {"name": "edit_file", "args": {"file_path": "/tmp/main.py"}, "id": "tc1"}
        msg = AIMessage(content="", tool_calls=[tc])
        state = {"messages": [msg]}
        assert _extract_modified_python_files(state) == ["/tmp/main.py"]

    def test_ignores_non_python_files(self):
        tc = {"name": "write_file", "args": {"file_path": "/tmp/readme.md"}, "id": "tc1"}
        msg = AIMessage(content="", tool_calls=[tc])
        state = {"messages": [msg]}
        assert _extract_modified_python_files(state) == []

    def test_ignores_other_tools(self):
        tc = {"name": "read_file", "args": {"file_path": "/tmp/test.py"}, "id": "tc1"}
        msg = AIMessage(content="", tool_calls=[tc])
        state = {"messages": [msg]}
        assert _extract_modified_python_files(state) == []

    def test_deduplicates_files(self):
        tc1 = {"name": "write_file", "args": {"file_path": "/tmp/a.py"}, "id": "tc1"}
        tc2 = {"name": "edit_file", "args": {"file_path": "/tmp/a.py"}, "id": "tc2"}
        msg = AIMessage(content="", tool_calls=[tc1, tc2])
        state = {"messages": [msg]}
        result = _extract_modified_python_files(state)
        assert result == ["/tmp/a.py"]

    def test_empty_messages(self):
        state = {"messages": []}
        assert _extract_modified_python_files(state) == []


class TestFindTestFiles:
    def test_finds_test_file_in_same_dir(self, tmp_path):
        src = tmp_path / "module.py"
        src.write_text("x = 1")
        test = tmp_path / "test_module.py"
        test.write_text("def test_x(): pass")
        result = _find_test_files([str(src)])
        assert str(test) in result

    def test_no_test_file(self, tmp_path):
        src = tmp_path / "module.py"
        src.write_text("x = 1")
        result = _find_test_files([str(src)])
        assert result == []

    def test_empty_input(self):
        assert _find_test_files([]) == []


class TestVerifyRouting:
    def test_errors_returns_agent(self):
        state = {"verify_errors": ["[语法] error"]}
        assert _verify_routing(state) == "agent"

    def test_no_errors_returns_end(self):
        state = {"verify_errors": None}
        assert _verify_routing(state) == END

    def test_empty_errors_returns_end(self):
        state = {"verify_errors": []}
        assert _verify_routing(state) == END
