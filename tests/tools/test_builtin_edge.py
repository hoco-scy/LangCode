"""tools.builtin — 内置工具边界用例补充测试

重要：builtin 工具返回 Pydantic 模型（FileContentResponse, SearchResponse 等），
不是字符串。断言必须使用模型属性（.success, .content, .files 等）。
"""

import pytest
from pathlib import Path

from LangCode.tools.builtin.file_read import read_file
from LangCode.tools.builtin.file_write import write_file
from LangCode.tools.builtin.file_edit import edit_file
from LangCode.tools.builtin.search import search_files, grep_content


# ── read_file 边界 ──

class TestReadFileEdgeCases:
    def test_read_binary_file_returns_response(self, tmp_path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        result = read_file.invoke({"file_path": str(f)})
        assert result.success is True

    def test_read_utf8_chinese(self, tmp_path):
        f = tmp_path / "chinese.py"
        f.write_text("# 中文注释\nprint('你好世界')", encoding="utf-8")
        result = read_file.invoke({"file_path": str(f)})
        assert result.success is True
        assert "中文注释" in result.content
        assert "你好世界" in result.content

    def test_read_with_offset_and_limit(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
        result = read_file.invoke({"file_path": str(f), "offset": 10, "limit": 5})
        assert result.success is True
        assert "line 9" in result.content  # offset=10 → 第10行是 line 9

    def test_read_directory_returns_error(self, tmp_path):
        result = read_file.invoke({"file_path": str(tmp_path)})
        assert result.success is False


# ── write_file 边界 ──

class TestWriteFileEdgeCases:
    def test_write_empty_content(self, tmp_path):
        f = tmp_path / "empty.txt"
        result = write_file.invoke({"file_path": str(f), "content": ""})
        assert f.exists()
        assert f.read_text(encoding="utf-8") == ""

    def test_write_unicode_content(self, tmp_path):
        f = tmp_path / "unicode.txt"
        content = "中文内容\n日本語\n한국어"
        result = write_file.invoke({"file_path": str(f), "content": content})
        assert f.read_text(encoding="utf-8") == content

    def test_write_nested_directory(self, tmp_path):
        f = tmp_path / "a" / "b" / "c" / "deep.txt"
        result = write_file.invoke({"file_path": str(f), "content": "deep"})
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "deep"

    def test_write_overwrites_existing(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")
        write_file.invoke({"file_path": str(f), "content": "new content"})
        assert f.read_text(encoding="utf-8") == "new content"


# ── edit_file 边界 ──

class TestEditFileEdgeCases:
    def test_edit_multiline_match(self, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "def foo():\n    pass",
            "new_text": "def foo():\n    return 42",
        })
        content = f.read_text(encoding="utf-8")
        assert "return 42" in content

    def test_edit_preserves_indentation(self, tmp_path):
        f = tmp_path / "indent.py"
        f.write_text("class A:\n    def method(self):\n        pass\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "        pass",
            "new_text": "        return True",
        })
        content = f.read_text(encoding="utf-8")
        assert "        return True" in content

    def test_edit_at_file_start(self, tmp_path):
        f = tmp_path / "start.py"
        f.write_text("#!/usr/bin/python\nprint('hello')\n", encoding="utf-8")
        result = edit_file.invoke({
            "file_path": str(f),
            "old_text": "#!/usr/bin/python",
            "new_text": "#!/usr/bin/python3",
        })
        content = f.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/python3")


# ── search_files 边界 ──

class TestSearchFilesEdgeCases:
    def test_glob_no_match(self, tmp_path):
        result = search_files.invoke({"pattern": "*.xyz", "directory": str(tmp_path)})
        assert result.success is True
        assert result.total == 0

    def test_glob_nested(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "deep.py").write_text("x", encoding="utf-8")
        result = search_files.invoke({"pattern": "**/*.py", "directory": str(tmp_path)})
        assert result.success is True
        assert any("deep.py" in f for f in result.files)

    def test_grep_no_match(self, tmp_path):
        (tmp_path / "test.py").write_text("hello world", encoding="utf-8")
        result = grep_content.invoke({"pattern": "nonexistent_xyz", "directory": str(tmp_path)})
        assert result.success is True

    def test_grep_with_context_lines(self, tmp_path):
        (tmp_path / "test.py").write_text("line1\nline2 TARGET line3\nline4", encoding="utf-8")
        result = grep_content.invoke({"pattern": "TARGET", "directory": str(tmp_path), "context_lines": 1})
        assert result.success is True
