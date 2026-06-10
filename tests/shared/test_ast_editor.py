"""shared/ast_editor.py — AST 结构化编辑测试"""

import pytest
import os

from LangCode.shared.ast_editor import ast_info, ast_find, ast_rename, ast_add_param, ast_add_method, ast_add_import


SAMPLE_PYTHON = '''\
import os
from typing import Optional

class Calculator:
    """简单计算器"""

    def __init__(self):
        self.result = 0

    def add(self, x: int, y: int) -> int:
        return x + y

    def multiply(self, a, b):
        return a * b

def hello(name: str) -> str:
    return f"Hello {name}"

def greet(name, greeting="Hi"):
    return f"{greeting}, {name}"

MAX_VALUE = 100
'''


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON, encoding="utf-8")
    return str(f)


class TestAstInfo:
    def test_returns_functions(self, sample_file):
        result = ast_info(sample_file)
        assert result["success"] is True
        func_names = [f["name"] for f in result["functions"]]
        assert "hello" in func_names
        assert "greet" in func_names

    def test_returns_classes(self, sample_file):
        result = ast_info(sample_file)
        assert result["success"] is True
        class_names = [c["name"] for c in result["classes"]]
        assert "Calculator" in class_names

    def test_returns_methods(self, sample_file):
        result = ast_info(sample_file)
        calculator = [c for c in result["classes"] if c["name"] == "Calculator"][0]
        assert "add" in calculator["methods"]
        assert "multiply" in calculator["methods"]

    def test_returns_imports(self, sample_file):
        result = ast_info(sample_file)
        assert len(result["imports"]) >= 2

    def test_returns_params(self, sample_file):
        result = ast_info(sample_file)
        add_func = [f for f in result["functions"] if f["name"] == "greet"][0]
        assert "name" in add_func["params"]
        assert "greeting" in add_func["params"]

    def test_file_not_found(self):
        result = ast_info("/nonexistent/file.py")
        assert result["success"] is False

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = ast_info(str(f))
        assert result["success"] is False


class TestAstFind:
    def test_find_function(self, sample_file):
        result = ast_find(sample_file, "function", "hello")
        assert result["success"] is True
        assert result["found"] == 1
        assert result["results"][0]["type"] == "function"

    def test_find_class(self, sample_file):
        result = ast_find(sample_file, "class", "Calculator")
        assert result["success"] is True
        assert result["found"] == 1

    def test_find_method(self, sample_file):
        result = ast_find(sample_file, "method", "add")
        assert result["success"] is True
        assert result["found"] == 1
        assert result["results"][0]["class"] == "Calculator"

    def test_find_variable(self, sample_file):
        result = ast_find(sample_file, "variable", "MAX_VALUE")
        assert result["success"] is True
        assert result["found"] == 1

    def test_find_not_found(self, sample_file):
        result = ast_find(sample_file, "function", "nonexistent")
        assert result["success"] is True
        assert result["found"] == 0


class TestAstRename:
    def test_rename_function(self, sample_file):
        result = ast_rename(sample_file, "hello", "greet_user")
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "def greet_user(" in content
        assert "def hello(" not in content

    def test_rename_variable(self, sample_file):
        result = ast_rename(sample_file, "MAX_VALUE", "LIMIT")
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "LIMIT" in content
        assert "MAX_VALUE" not in content

    def test_rename_not_found(self, sample_file):
        result = ast_rename(sample_file, "nonexistent", "new_name")
        assert result.success is False

    def test_rename_preserves_structure(self, sample_file):
        ast_rename(sample_file, "greet", "welcome")
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "class Calculator:" in content
        assert "def welcome(" in content


class TestAstAddParam:
    def test_add_param_with_default(self, sample_file):
        result = ast_add_param(sample_file, "hello", "greeting", '"Hello"')
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "greeting=" in content

    def test_add_param_without_default(self, sample_file):
        result = ast_add_param(sample_file, "hello", "prefix")
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "prefix" in content

    def test_add_param_after_self(self, sample_file):
        result = ast_add_param(sample_file, "add", "verbose", "False", position=0)
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "self, verbose" in content

    def test_add_duplicate_param(self, sample_file):
        result = ast_add_param(sample_file, "greet", "name")
        assert result.success is False
        assert "已存在" in result.error


class TestAstAddMethod:
    def test_add_method(self, sample_file):
        method = "def subtract(self, x, y):\n    return x - y"
        result = ast_add_method(sample_file, "Calculator", method)
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "def subtract" in content

    def test_add_method_class_not_found(self, sample_file):
        result = ast_add_method(sample_file, "Nonexistent", "def foo(self): pass")
        assert result.success is False


class TestAstAddImport:
    def test_add_new_import(self, sample_file):
        result = ast_add_import(sample_file, "import json")
        assert result.success is True
        with open(sample_file, encoding="utf-8") as f:
            content = f.read()
        assert "import json" in content

    def test_duplicate_import(self, sample_file):
        result = ast_add_import(sample_file, "import os")
        assert result.success is False
        assert "已存在" in result.error
