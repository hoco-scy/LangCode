"""tools/ast — AST 结构化编辑工具（LangCode 差异化功能）。

基于 tree-sitter 的代码分析和编辑，支持 Python 代码的结构化操作。
通过 LanguagePlugin 接口支持多语言扩展。
"""

from LangCode.tools.ast.tools import ast_tools
from LangCode.tools.ast.languages import (
    LanguagePlugin, PythonPlugin, register_plugin, get_plugin, get_all_plugins,
)

__all__ = [
    "ast_tools",
    "LanguagePlugin", "PythonPlugin",
    "register_plugin", "get_plugin", "get_all_plugins",
]
