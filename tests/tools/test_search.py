"""tools.builtin.search — search_files + grep_content 测试"""

import os
import pytest
from unittest.mock import patch, MagicMock

from LangCode.tools.builtin.search import (
    search_files, grep_content, _should_exclude, _EXCLUDED_DIRS,
    _grep_with_rg, _grep_with_python,
)


class TestShouldExclude:
    def test_excluded_dir(self):
        assert _should_exclude("src/__pycache__/module.pyc") is True

    def test_git_dir(self):
        assert _should_exclude(".git/HEAD") is True

    def test_node_modules(self):
        assert _should_exclude("node_modules/package/index.js") is True

    def test_normal_file(self):
        assert _should_exclude("src/main.py") is False

    def test_nested_normal(self):
        assert _should_exclude("src/tools/builtin/search.py") is False

    def test_venv_excluded(self):
        assert _should_exclude(".venv/lib/python3.py") is True


class TestSearchFiles:
    def test_basic_glob(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()

        result = search_files.invoke({
            "pattern": "*.py",
            "directory": str(tmp_path),
            "max_results": 100,
        })
        assert result.success is True
        assert len(result.files) == 2

    def test_recursive_glob(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").touch()
        (tmp_path / "top.py").touch()

        result = search_files.invoke({
            "pattern": "**/*.py",
            "directory": str(tmp_path),
            "max_results": 100,
        })
        assert result.success is True
        assert len(result.files) == 2

    def test_max_results(self, tmp_path):
        for i in range(20):
            (tmp_path / f"f{i}.py").touch()

        result = search_files.invoke({
            "pattern": "*.py",
            "directory": str(tmp_path),
            "max_results": 5,
        })
        assert len(result.files) == 5

    def test_no_matches(self, tmp_path):
        result = search_files.invoke({
            "pattern": "*.xyz",
            "directory": str(tmp_path),
        })
        assert result.success is True
        assert len(result.files) == 0

    def test_excludes_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "cached.pyc").touch()
        (tmp_path / "real.py").touch()

        result = search_files.invoke({
            "pattern": "**/*.pyc",
            "directory": str(tmp_path),
        })
        assert len(result.files) == 0

    def test_nonexistent_directory(self, tmp_path):
        result = search_files.invoke({
            "pattern": "*.py",
            "directory": str(tmp_path / "nonexistent"),
        })
        assert result.success is True
        assert len(result.files) == 0


class TestGrepContent:
    def test_basic_search(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n\ndef world():\n    pass\n")

        result = grep_content.invoke({
            "pattern": "def hello",
            "directory": str(tmp_path),
            "max_results": 10,
        })
        assert result.success is True
        assert len(result.files) > 0

    def test_no_matches(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("nothing here\n")

        result = grep_content.invoke({
            "pattern": "nonexistent_pattern_xyz",
            "directory": str(tmp_path),
            "max_results": 10,
        })
        assert result.success is True
        assert len(result.files) == 0

    def test_invalid_regex(self, tmp_path):
        result = grep_content.invoke({
            "pattern": "[invalid",
            "directory": str(tmp_path),
        })
        # 两种路径：ripgrep 返回错误 或 Python re 返回错误
        # 结果应包含错误信息
        assert result.success is False or (result.error and "正则" in result.error)

    def test_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("hello world\n")
        (tmp_path / "b.txt").write_text("hello world\n")

        result = grep_content.invoke({
            "pattern": "hello",
            "directory": str(tmp_path),
            "glob_filter": "*.py",
            "max_results": 10,
        })
        assert result.success is True
        # 只应匹配 .py 文件
        assert all("a.py" in f for f in result.files)


class TestGrepWithPython:
    def test_basic(self, tmp_path):
        (tmp_path / "test.py").write_text("def foo():\n    return 42\n")

        result = _grep_with_python("def foo", str(tmp_path), "", 10, 0)
        assert result.success is True
        assert len(result.files) > 0

    def test_context_lines(self, tmp_path):
        (tmp_path / "test.py").write_text("line1\nline2\ntarget\nline4\nline5\n")

        result = _grep_with_python("target", str(tmp_path), "", 10, 2)
        assert result.success is True

    def test_max_results(self, tmp_path):
        content = "\n".join([f"match line {i}" for i in range(100)])
        (tmp_path / "test.py").write_text(content)

        result = _grep_with_python("match", str(tmp_path), "", 5, 0)
        assert result.success is True
