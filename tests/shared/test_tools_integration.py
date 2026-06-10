"""shared/tools.py — 文件工具集成测试（使用 tmp_path）"""

import pytest
from LangCode.shared.tools import read_file, write_file, edit_file, search_files, execute_shell, run_python


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
        result = write_file.invoke({"file_path": str(f), "content": "数据"})
        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "数据"

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = write_file.invoke({"file_path": str(f), "content": "嵌套"})
        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "嵌套"


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
            "old_text": "不存在的文本",
            "new_text": "y",
        })
        assert result["success"] is False
        assert result["error"]  # 有错误信息即可

    def test_edit_multiple_matches(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "x = 1",
            "new_text": "y = 2",
        })
        assert result["success"] is False
        assert "2 处" in result["error"]

    def test_edit_file_not_found(self, tmp_path):
        result = edit_file.invoke({
            "file_path": str(tmp_path / "nope.py"),
            "old_text": "a",
            "new_text": "b",
        })
        assert result["success"] is False
        assert "不存在" in result["error"]


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
        assert "禁止" in result["error"]

    def test_sandbox_blocks_subprocess(self):
        result = run_python.invoke({"code": "import subprocess", "timeout": 10})
        assert result["success"] is False

    def test_syntax_error(self):
        result = run_python.invoke({"code": "def foo(", "timeout": 10})
        assert result["success"] is False
