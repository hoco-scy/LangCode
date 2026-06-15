"""tools/builtin — 内置工具集合。

每工具一个文件，自包含输入模型 + 工具实现。
通过 all_tools 列表统一导出。
"""

from LangCode.tools.builtin.file_read import read_file
from LangCode.tools.builtin.file_write import write_file
from LangCode.tools.builtin.file_edit import edit_file
from LangCode.tools.builtin.search import search_files, grep_content
from LangCode.tools.builtin.shell import execute_shell
from LangCode.tools.builtin.python import run_python
from LangCode.tools.builtin.web import fetch_api, web_search
from LangCode.tools.builtin.git import git_tools
from LangCode.tools.builtin.delegate import delegate_tools

all_tools = [read_file, fetch_api, web_search, execute_shell, run_python, write_file, edit_file, search_files, grep_content] + git_tools + delegate_tools

__all__ = [
    "read_file", "write_file", "edit_file",
    "search_files", "grep_content", "execute_shell", "run_python",
    "fetch_api", "web_search",
    "git_tools", "delegate_tools",
    "all_tools",
]
