# -*- coding: utf-8 -*-
"""shared/tools.py - file tools integration tests (uses tmp_path)"""

import sys
import os
import subprocess
import pytest
from LangCode.shared.tools import (
    read_file, write_file, edit_file, search_files,
    execute_shell, run_python,
)

# Build Chinese strings via chr() so the source stays ASCII-only.
# This avoids mojibake when the file is read with a non-UTF-8 locale (e.g. cp936).
_ZH = lambda *cps: "".join(chr(c) for c in cps)


class TestReadFile:
    def test_read_success(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = read_file.invoke({"file_path": str(f)})
        assert result["success"] is True
        assert result["content"] == "hello world"

    def test_file_not_found(self, tmp_path):
        result = read_file.invoke({"file_path": str(tmp_path / "nope.txt")})
        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestWriteFile:
    def test_write_creates_file(self, tmp_path):
        f = tmp_path / "out.txt"
        content = _ZH(0x6570, 0x636E)  # 数据
        result = write_file.invoke({"file_path": str(f), "content": content})
        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == content

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        content = _ZH(0x5D4C, 0x5957)  # 嵌套
        result = write_file.invoke({"file_path": str(f), "content": content})
        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == content


class TestEditFile:
    def test_edit_single_match(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def foo():\n    pass\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "pass",
            "new_text": "return 42",
        })
        assert result["success"] is True
        assert "return 42" in f.read_text(encoding="utf-8")

    def test_edit_no_match(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "not found",
            "new_text": "y",
        })
        assert result["success"] is False
        assert result["error"]

    def test_edit_multiple_matches(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "x = 1",
            "new_text": "y = 2",
        })
        assert result["success"] is False

    def test_edit_file_not_found(self, tmp_path):
        result = edit_file.invoke({
            "file_path": str(tmp_path / "nope.py"),
            "old_text": "a",
            "new_text": "b",
        })
        assert result["success"] is False


class TestSearchFiles:
    def test_search_finds_files(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = search_files.invoke({"pattern": "*.py", "directory": str(tmp_path)})
        assert result["success"] is True
        assert result["total"] == 2

    def test_search_no_results(self, tmp_path):
        result = search_files.invoke({"pattern": "*.xyz", "directory": str(tmp_path)})
        assert result["success"] is True
        assert result["total"] == 0

    def test_search_filters_pycache(self, tmp_path):
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.cpython-311.pyc").write_text("")
        (tmp_path / "real.py").write_text("")
        result = search_files.invoke({"pattern": "**/*", "directory": str(tmp_path)})
        assert result["success"] is True
        assert all("__pycache__" not in f for f in result["files"])


class TestExecuteShell:
    def test_echo_success(self):
        result = execute_shell.invoke({"command": "echo hello", "timeout": 5})
        assert result["success"] is True
        assert "hello" in result["output"]

    def test_chinese_output_decoded_correctly(self):
        """execute_shell should decode Chinese stdout without mojibake.

        Uses ``python -c`` so the output encoding is deterministic (Python
        respects PYTHONIOENCODING / PYTHONUTF8) and the bytes arriving in the
        parent process match the encoding returned by ``_get_shell_encoding()``.
        """
        # 当前目录
        expected = _ZH(0x5F53, 0x524D, 0x76EE, 0x5F55)
        cmd = '%s -c "print(%r)"' % (sys.executable, expected)
        result = execute_shell.invoke({"command": cmd, "timeout": 5})
        assert result["success"] is True
        assert expected in result["output"]
        assert chr(0xFFFD) not in result["output"]  # no replacement chars

    def test_chinese_mixed_chars_decoded_correctly(self):
        # 测试通过
        expected = _ZH(0x6D4B, 0x8BD5, 0x901A, 0x8FC7)
        cmd = '%s -c "print(%r)"' % (sys.executable, expected)
        result = execute_shell.invoke({"command": cmd, "timeout": 5})
        assert result["success"] is True
        assert expected in result["output"]

    def test_nonzero_exit(self):
        result = execute_shell.invoke({"command": "exit 1", "timeout": 5})
        assert result["success"] is False
        assert result["return_code"] == 1


class TestRunPython:
    def test_print_success(self):
        result = run_python.invoke({"code": "print(42)", "timeout": 10})
        assert result["success"] is True
        assert "42" in result["output"]

    def test_sandbox_blocks_os(self):
        result = run_python.invoke({"code": "import os; os.system('echo hacked')", "timeout": 10})
        assert result["success"] is False

    def test_sandbox_blocks_subprocess(self):
        result = run_python.invoke({"code": "import subprocess", "timeout": 10})
        assert result["success"] is False

    def test_syntax_error(self):
        result = run_python.invoke({"code": "def foo(", "timeout": 10})
        assert result["success"] is False

