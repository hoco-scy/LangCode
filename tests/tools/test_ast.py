"""tools.ast — AST 结构化编辑工具测试"""

import pytest
from pathlib import Path

from LangCode.tools.ast.editor import (
    ast_info, ast_find, ast_rename,
    ast_add_param, ast_add_method, ast_add_import,
)


@pytest.fixture
def py_file(tmp_path):
    """创建测试用 Python 文件"""
    code = '''"""测试模块"""

import os
from pathlib import Path

class Calculator:
    """简单计算器"""

    def __init__(self):
        self.history = []

    def add(self, a, b):
        """加法"""
        result = a + b
        self.history.append(result)
        return result

    def subtract(self, a, b):
        return a - b

def greet(name):
    return f"Hello, {name}!"

MAX_RETRIES = 3
'''
    f = tmp_path / "sample.py"
    f.write_text(code, encoding="utf-8")
    return str(f)


# ── ast_info ──

class TestAstInfo:
    def test_returns_functions_and_classes(self, py_file):
        result = ast_info(py_file)
        func_names = [f.name for f in result.functions]
        class_names = [c.name for c in result.classes]
        assert "greet" in func_names
        assert "add" not in func_names  # add 是方法，不在顶层函数中
        assert "Calculator" in class_names

    def test_returns_imports(self, py_file):
        result = ast_info(py_file)
        import_texts = result.imports  # imports 是字符串列表
        assert any("os" in t for t in import_texts)
        assert any("Path" in t for t in import_texts)

    def test_nonexistent_file(self):
        result = ast_info("/nonexistent/file.py")
        assert result.error is not None

    def test_non_python_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("not python", encoding="utf-8")
        result = ast_info(str(f))
        assert result.error is not None


# ── ast_find ──

class TestAstFind:
    def test_find_function(self, py_file):
        result = ast_find(py_file, "function", "greet")
        assert len(result.results) >= 1
        assert result.results[0].name == "greet"
        assert result.results[0].line > 0

    def test_find_class(self, py_file):
        result = ast_find(py_file, "class", "Calculator")
        assert len(result.results) >= 1
        assert result.results[0].name == "Calculator"

    def test_find_method(self, py_file):
        result = ast_find(py_file, "method", "add")
        assert len(result.results) >= 1
        assert result.results[0].name == "add"

    def test_find_nonexistent(self, py_file):
        result = ast_find(py_file, "function", "nonexistent_func")
        assert len(result.results) == 0


# ── ast_rename ──

class TestAstRename:
    def test_rename_function(self, py_file):
        result = ast_rename(py_file, "greet", "say_hello")
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "def say_hello" in content
        assert "greet" not in content

    def test_rename_class(self, py_file):
        result = ast_rename(py_file, "Calculator", "Calc")
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "class Calc" in content
        assert "Calculator" not in content

    def test_rename_nonexistent(self, py_file):
        result = ast_rename(py_file, "no_such_name", "new_name")
        assert result.success is False or result.changes == 0


# ── ast_add_param ──

class TestAstAddParam:
    def test_add_param_to_function(self, py_file):
        result = ast_add_param(py_file, "greet", "greeting", default_value='"Hello"')
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "greeting" in content

    def test_add_param_to_method(self, py_file):
        result = ast_add_param(py_file, "add", "verbose", default_value="False")
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "verbose" in content

    def test_add_param_nonexistent_func(self, py_file):
        result = ast_add_param(py_file, "no_such_func", "x")
        assert result.success is False or result.error is not None


# ── ast_add_method ──

class TestAstAddMethod:
    def test_add_method_to_class(self, py_file):
        method_code = '''    def multiply(self, a, b):
        return a * b'''
        result = ast_add_method(py_file, "Calculator", method_code)
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "def multiply" in content

    def test_add_method_nonexistent_class(self, py_file):
        result = ast_add_method(py_file, "NoSuchClass", "    def x(self): pass")
        assert result.success is False or result.error is not None


# ── ast_add_import ──

class TestAstAddImport:
    def test_add_new_import(self, py_file):
        result = ast_add_import(py_file, "import json")
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "import json" in content

    def test_duplicate_import_returns_error(self, py_file):
        # os 已存在，应返回失败
        result = ast_add_import(py_file, "import os")
        assert result.success is False
        assert "已存在" in result.error

    def test_add_from_import(self, py_file):
        result = ast_add_import(py_file, "from typing import List, Dict")
        assert result.success is True
        content = Path(py_file).read_text(encoding="utf-8")
        assert "from typing import List, Dict" in content
