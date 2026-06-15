"""LanguagePlugin — AST 语言插件抽象接口。

每个语言实现（Python, TypeScript, Go...）提供一个插件类。
通过 tree-sitter 实现结构化代码分析和编辑。

扩展新语言只需:
1. 创建 languages/xxx.py，实现 LanguagePlugin
2. 在 languages/__init__.py 中注册
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass


@dataclass
class FunctionInfo:
    name: str
    line: int
    params: list[str]
    is_method: bool = False
    class_name: str = ""


@dataclass
class ClassInfo:
    name: str
    line: int
    methods: list[str]
    bases: list[str]


@dataclass
class ImportInfo:
    line: int
    module: str
    names: list[str]


@dataclass
class FileInfo:
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    imports: list[ImportInfo]
    variables: list[str]


@dataclass
class EditResult:
    success: bool
    message: str
    modified_lines: list[int] = None

    def __post_init__(self):
        if self.modified_lines is None:
            self.modified_lines = []


class LanguagePlugin(ABC):
    """AST 语言插件接口。"""

    @property
    @abstractmethod
    def language_name(self) -> str:
        """语言名称（如 "python", "typescript"）"""
        ...

    @property
    @abstractmethod
    def extensions(self) -> set[str]:
        """支持的文件扩展名（如 {".py"}）"""
        ...

    @abstractmethod
    def analyze(self, file_path: str) -> FileInfo:
        """分析文件结构：函数、类、import、变量"""
        ...

    @abstractmethod
    def find_element(
        self, file_path: str, element_type: str, name: str
    ) -> list[dict]:
        """查找代码元素，返回 [{line, column, end_line, ...}]"""
        ...

    @abstractmethod
    def rename(
        self, file_path: str, old_name: str, new_name: str
    ) -> EditResult:
        """重命名标识符（同作用域内）"""
        ...

    @abstractmethod
    def add_parameter(
        self, file_path: str, func_name: str, param_name: str,
        default: Optional[str] = None, position: Optional[int] = None,
    ) -> EditResult:
        """为函数添加参数"""
        ...

    @abstractmethod
    def add_method(
        self, file_path: str, class_name: str, method_code: str,
    ) -> EditResult:
        """在类中添加方法"""
        ...

    @abstractmethod
    def add_import(
        self, file_path: str, import_statement: str,
    ) -> EditResult:
        """添加 import 语句（避免重复）"""
        ...
