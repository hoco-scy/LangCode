"""shared/tools.py — 纯函数和 Pydantic 模型测试"""

import pytest
from pydantic import ValidationError

from LangCode.shared.tools import (
    _extract_user_error,
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
