"""AST 语言插件注册。"""

from LangCode.tools.ast.languages.interface import LanguagePlugin
from LangCode.tools.ast.languages.python import PythonPlugin

_PLUGINS: dict[str, LanguagePlugin] = {}


def register_plugin(plugin: LanguagePlugin) -> None:
    """注册语言插件。"""
    for ext in plugin.extensions:
        _PLUGINS[ext] = plugin


def get_plugin(file_path: str) -> LanguagePlugin | None:
    """根据文件扩展名获取对应插件。"""
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    return _PLUGINS.get(ext)


def get_all_plugins() -> list[LanguagePlugin]:
    return list({p for p in _PLUGINS.values()})


# 注册内置插件
register_plugin(PythonPlugin())

__all__ = [
    "LanguagePlugin", "PythonPlugin",
    "register_plugin", "get_plugin", "get_all_plugins",
]
