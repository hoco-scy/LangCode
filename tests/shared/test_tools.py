"""shared/tools.py — 纯函数和 Pydantic 模型测试"""

import sys
import pytest
from unittest.mock import patch
from pydantic import ValidationError

from LangCode.shared.tools import (
    _extract_user_error, _get_shell_encoding, _GIT_ENCODING,
    ReadFileInput, WriteFileInput, EditFileInput,
    SearchFilesInput, RunPythonInput, RunCommandInput,
)


# ============================================================
#  _extract_user_error 纯函数测试
# ============================================================

class TestExtractUserError:
    def test_none_returns_none(self):
        assert _extract_user_error(None) is None

    def test_empty_string_returns_none(self):
        assert _extract_user_error("") is None

    def test_extracts_last_error_line(self):
        stderr = 'Traceback (most recent call last):\n  File "test.py", line 1\n    x = 1 / 0\nZeroDivisionError: division by zero'
        result = _extract_user_error(stderr)
        assert result == "ZeroDivisionError: division by zero"

    def test_handles_memory_error(self):
        result = _extract_user_error("MemoryError")
        assert result == "MemoryError"

    def test_skips_traceback_lines(self):
        stderr = '  File "sandbox.py", line 5\n    exec(code)\nValueError: bad value'
        result = _extract_user_error(stderr)
        assert result == "ValueError: bad value"


# ============================================================
#  Pydantic 输入模型测试
# ============================================================

class TestPydanticModels:
    def test_read_file_input_required(self):
        with pytest.raises(ValidationError):
            ReadFileInput()

    def test_read_file_input_defaults(self):
        inp = ReadFileInput(file_path="test.py")
        assert inp.encode == "utf-8"
        assert inp.file_path == "test.py"

    def test_write_file_input_required(self):
        with pytest.raises(ValidationError):
            WriteFileInput()

    def test_edit_file_input_required(self):
        with pytest.raises(ValidationError):
            EditFileInput(file_path="x", old_text="a")

    def test_run_python_timeout_constraints(self):
        inp = RunPythonInput(code="print(1)")
        assert inp.timeout == 15
        with pytest.raises(ValidationError):
            RunPythonInput(code="x", timeout=0)
        with pytest.raises(ValidationError):
            RunPythonInput(code="x", timeout=100)

    def test_search_files_defaults(self):
        inp = SearchFilesInput(pattern="*.py")
        assert inp.directory == "."

    def test_run_command_required(self):
        with pytest.raises(ValidationError):
            RunCommandInput()


# ============================================================
#  编码常量与辅助函数测试
# ============================================================

class TestEncodingHelpers:
    def test_git_encoding_is_utf8(self):
        """Git 通过 GIT_IOENCODING 强制 UTF-8，常量必须为 utf-8"""
        assert _GIT_ENCODING == "utf-8"

    @patch("LangCode.shared.tools._platform.system", return_value="Linux")
    def test_shell_encoding_linux_returns_utf8(self, _mock):
        assert _get_shell_encoding() == "utf-8"

    @patch("LangCode.shared.tools._platform.system", return_value="Windows")
    def test_shell_encoding_windows_returns_system_codepage(self, _mock):
        enc = _get_shell_encoding()
        # Windows 中文系统返回 'cp936'，英文系统返回 'cp1252' 等，只需非 utf-8 即可
        assert enc != "utf-8"

    @patch("LangCode.shared.tools._platform.system", return_value="Darwin")
    def test_shell_encoding_darwin_returns_utf8(self, _mock):
        assert _get_shell_encoding() == "utf-8"
