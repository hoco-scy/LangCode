"""Python 语言插件 — 包装现有 tree-sitter editor。"""

from __future__ import annotations

from typing import Optional

from LangCode.tools.ast.languages.interface import (
    LanguagePlugin, FileInfo, FunctionInfo, ClassInfo, ImportInfo, EditResult,
)
from LangCode.tools.ast import editor


class PythonPlugin(LanguagePlugin):
    """Python tree-sitter AST 插件。"""

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def extensions(self) -> set[str]:
        return {".py"}

    def analyze(self, file_path: str) -> FileInfo:
        result = editor.ast_info(file_path)
        functions = [
            FunctionInfo(
                name=f.name, line=f.line, params=f.params or [],
                is_method=False, class_name="",
            )
            for f in result.functions
        ]
        classes = [
            ClassInfo(
                name=c.name, line=c.line,
                methods=c.methods or [], bases=[],
            )
            for c in result.classes
        ]
        # imports 是 list[str]（原始 import 语句），转为 ImportInfo
        imports = [
            ImportInfo(line=0, module=s, names=[])
            for s in result.imports
        ]
        return FileInfo(
            functions=functions,
            classes=classes,
            imports=imports,
            variables=[],
        )

    def find_element(
        self, file_path: str, element_type: str, name: str
    ) -> list[dict]:
        result = editor.ast_find(file_path, element_type, name)
        return [
            {
                "line": r.line,
                "end_line": r.end_line,
                "name": r.name,
                "type": r.type,
                "class_name": r.class_name,
                "text_preview": r.text_preview,
            }
            for r in result.results
        ]

    def rename(
        self, file_path: str, old_name: str, new_name: str
    ) -> EditResult:
        result = editor.ast_rename(file_path, old_name, new_name)
        return EditResult(
            success=result.success,
            message=result.message,
            modified_lines=result.modified_lines or [],
        )

    def add_parameter(
        self, file_path: str, func_name: str, param_name: str,
        default: Optional[str] = None, position: Optional[int] = None,
    ) -> EditResult:
        result = editor.ast_add_param(file_path, func_name, param_name, default, position)
        return EditResult(
            success=result.success,
            message=result.message,
            modified_lines=result.modified_lines or [],
        )

    def add_method(
        self, file_path: str, class_name: str, method_code: str,
    ) -> EditResult:
        result = editor.ast_add_method(file_path, class_name, method_code)
        return EditResult(
            success=result.success,
            message=result.message,
            modified_lines=result.modified_lines or [],
        )

    def add_import(
        self, file_path: str, import_statement: str,
    ) -> EditResult:
        result = editor.ast_add_import(file_path, import_statement)
        return EditResult(
            success=result.success,
            message=result.message,
            modified_lines=result.modified_lines or [],
        )
