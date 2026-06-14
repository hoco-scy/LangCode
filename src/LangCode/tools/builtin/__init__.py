"""tools/builtin — 内置工具集合。

每工具一个文件，自包含输入模型 + 工具实现。
通过 all_tools 列表统一导出。
"""

from LangCode.tools.builtin.file_read import read_file
from LangCode.tools.builtin.file_write import write_file
from LangCode.tools.builtin.file_edit import edit_file
from LangCode.tools.builtin.search import search_files
from LangCode.tools.builtin.shell import execute_shell
from LangCode.tools.builtin.python import run_python
from LangCode.tools.builtin.web import fetch_api

all_tools = [read_file, fetch_api, execute_shell, run_python, write_file, edit_file, search_files]

__all__ = [
    "read_file", "write_file", "edit_file",
    "search_files", "execute_shell", "run_python", "fetch_api",
    "all_tools",
]
