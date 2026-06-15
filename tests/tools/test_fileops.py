"""tools.builtin 文件操作工具 — file_read + file_write + file_edit 测试"""

import os
import pytest
from pathlib import Path

from LangCode.tools.builtin.file_read import read_file
from LangCode.tools.builtin.file_write import write_file
from LangCode.tools.builtin.file_edit import edit_file


class TestReadFile:
    def test_read_basic(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\n")

        result = read_file.invoke({"file_path": str(f)})
        content = result.content if hasattr(result, "content") else str(result)
        assert "line1" in content
        assert "line2" in content
        assert "line3" in content

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = read_file.invoke({"file_path": str(f), "offset": 2, "limit": 2})
        content = result.content if hasattr(result, "content") else str(result)
        # offset 2 应跳过前2行
        assert "line3" in content or "3" in content

    def test_read_nonexistent(self, tmp_path):
        result = read_file.invoke({"file_path": str(tmp_path / "nope.py")})
        assert result.success is False

    def test_read_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")

        result = read_file.invoke({"file_path": str(f)})
        assert result is not None

    def test_read_returns_success(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("content")
        result = read_file.invoke({"file_path": str(f)})
        assert result.success is True


class TestWriteFile:
    def test_write_creates_file(self, tmp_path):
        f = tmp_path / "new.py"
        result = write_file.invoke({
            "file_path": str(f),
            "content": "print('hello')\n",
        })
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "print('hello')\n"

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "deep" / "nested" / "file.py"
        write_file.invoke({
            "file_path": str(f),
            "content": "content",
        })
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "content"

    def test_write_overwrites(self, tmp_path):
        f = tmp_path / "exists.py"
        f.write_text("old content")
        write_file.invoke({
            "file_path": str(f),
            "content": "new content",
        })
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_returns_success(self, tmp_path):
        f = tmp_path / "out.py"
        result = write_file.invoke({
            "file_path": str(f),
            "content": "data",
        })
        assert result.success is True


class TestEditFile:
    def test_basic_edit(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n")

        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "pass",
            "new_text": "return 'hello'",
        })
        assert f.read_text(encoding="utf-8") == "def hello():\n    return 'hello'\n"

    def test_no_match(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n")

        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "nonexistent",
            "new_text": "replacement",
        })
        assert result.success is False

    def test_multiple_match_error(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("pass\npass\n")

        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "pass",
            "new_text": "ok",
        })
        assert result.success is False

    def test_edit_nonexistent(self, tmp_path):
        result = edit_file.invoke({
            "file_path": str(tmp_path / "nope.py"),
            "old_text": "x",
            "new_text": "y",
        })
        assert result.success is False

    def test_edit_preserves_rest(self, tmp_path):
        f = tmp_path / "test.py"
        original = "line1\nline2\nline3\n"
        f.write_text(original)

        edit_file.invoke({
            "file_path": str(f),
            "old_text": "line2",
            "new_text": "LINE2",
        })
        content = f.read_text(encoding="utf-8")
        assert "line1" in content
        assert "LINE2" in content
        assert "line3" in content
