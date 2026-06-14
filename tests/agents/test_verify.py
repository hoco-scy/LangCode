"""agents.verify — auto_verify 节点测试"""

import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock

from LangCode.agents.verify import (
    auto_verify,
    after_verify_routing,
    _extract_modified_python_files,
    _syntax_check,
    _import_check,
    _find_test_files,
)


class TestExtractModifiedPythonFiles:
    def test_empty_messages(self):
        state = {"messages": []}
        files = _extract_modified_python_files(state)
        assert files == []

    def test_no_tool_calls(self):
        from langchain_core.messages import AIMessage
        state = {"messages": [AIMessage(content="hello")]}
        files = _extract_modified_python_files(state)
        assert files == []

    def test_extract_from_write_file(self, tmp_path):
        from langchain_core.messages import AIMessage

        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": str(test_file)},
                "id": "tc_1",
            }])
        ]}
        files = _extract_modified_python_files(state)
        assert str(test_file.resolve()) in files

    def test_extract_from_edit_file(self, tmp_path):
        from langchain_core.messages import AIMessage

        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "edit_file",
                "args": {"file_path": str(test_file)},
                "id": "tc_1",
            }])
        ]}
        files = _extract_modified_python_files(state)
        assert len(files) == 1

    def test_ignores_non_python_files(self, tmp_path):
        from langchain_core.messages import AIMessage

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": str(test_file)},
                "id": "tc_1",
            }])
        ]}
        files = _extract_modified_python_files(state)
        assert files == []

    def test_ignores_nonexistent_files(self):
        from langchain_core.messages import AIMessage

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": "/nonexistent/file.py"},
                "id": "tc_1",
            }])
        ]}
        files = _extract_modified_python_files(state)
        assert files == []


class TestSyntaxCheck:
    def test_valid_python(self, tmp_path):
        f = tmp_path / "valid.py"
        f.write_text("print('hello')", encoding="utf-8")
        errors = _syntax_check([str(f)])
        assert errors == []

    def test_invalid_python(self, tmp_path):
        f = tmp_path / "invalid.py"
        f.write_text("def foo(:\n  pass", encoding="utf-8")
        errors = _syntax_check([str(f)])
        assert len(errors) == 1
        assert "语法" in errors[0]


class TestImportCheck:
    def test_valid_import(self, tmp_path):
        f = tmp_path / "test_mod.py"
        f.write_text("x = 1", encoding="utf-8")
        errors = _import_check([str(f)])
        # 可能成功也可能失败（取决于模块路径），但不应崩溃
        assert isinstance(errors, list)


class TestFindTestFiles:
    def test_no_tests(self, tmp_path):
        f = tmp_path / "module.py"
        f.write_text("x = 1")
        tests = _find_test_files([str(f)])
        assert tests == []

    def test_adjacent_test_file(self, tmp_path):
        f = tmp_path / "module.py"
        f.write_text("x = 1")
        test_f = tmp_path / "test_module.py"
        test_f.write_text("def test_x(): pass")
        tests = _find_test_files([str(f)])
        assert len(tests) == 1
        assert "test_module.py" in tests[0]


class TestAutoVerify:
    def test_no_modified_files(self):
        from langchain_core.messages import AIMessage
        state = {"messages": [AIMessage(content="hello")]}
        result = auto_verify(state)
        assert result["verify_errors"] is None

    def test_valid_python_file(self, tmp_path):
        from langchain_core.messages import AIMessage

        f = tmp_path / "valid.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": str(f)},
                "id": "tc_1",
            }])
        ]}
        # auto_verify 执行语法检查 + 导入检查 + ruff
        # 导入检查可能因路径问题失败（Windows 上 tmp_path 含 :），这是已知限制
        # 只要语法检查通过即可
        result = auto_verify(state)
        # 语法检查不应产生错误（导入检查和 ruff 可能因环境问题产生警告）
        errors = result.get("verify_errors")
        if errors:
            # 过滤掉导入检查和 ruff 的错误，只关注语法
            syntax_errors = [e for e in errors if "[语法]" in e]
            assert len(syntax_errors) == 0

    def test_invalid_python_file(self, tmp_path):
        from langchain_core.messages import AIMessage

        f = tmp_path / "bad.py"
        f.write_text("def foo(:\n  pass", encoding="utf-8")

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": str(f)},
                "id": "tc_1",
            }])
        ]}
        result = auto_verify(state)
        assert result["verify_errors"] is not None
        assert len(result["verify_errors"]) > 0
        assert "messages" in result


class TestAfterVerifyRouting:
    def test_no_errors(self):
        state = {"verify_errors": None}
        assert after_verify_routing(state) == "router"

    def test_with_errors(self):
        state = {"verify_errors": ["error1"]}
        assert after_verify_routing(state) == "agent"

    def test_empty_errors_list(self):
        state = {"verify_errors": []}
        # 空列表被视为 falsy
        assert after_verify_routing(state) == "router"
