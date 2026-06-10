"""AST 结构化编辑工具：LangChain 工具包装器"""

from typing import Optional

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.ast_editor import (
    ast_info as _ast_info,
    ast_find as _ast_find,
    ast_rename as _ast_rename,
    ast_add_param as _ast_add_param,
    ast_add_method as _ast_add_method,
    ast_add_import as _ast_add_import,
)
from LangCode.shared.schemas import (
    AstInfoResponse, AstFindResponse, AstEditResponse,
)
from LangCode.shared.logger import get_logger

log = get_logger("ast_tools")


class AstInfoInput(BaseModel):
    file_path: str = Field(description="要分析的 Python 文件路径")


@tool("ast_info", args_schema=AstInfoInput)
def ast_info(file_path: str) -> AstInfoResponse:
    """分析 Python 文件的 AST 结构，返回函数、类、import 等信息。
    用于理解代码结构，比 read_file 更适合了解代码组织。"""
    return _ast_info(file_path)


class AstFindInput(BaseModel):
    file_path: str = Field(description="要搜索的 Python 文件路径")
    target_type: str = Field(description="查找类型: function(函数), class(类), method(方法), variable(变量)")
    name: str = Field(description="要查找的名称")


@tool("ast_find", args_schema=AstFindInput)
def ast_find(file_path: str, target_type: str, name: str) -> AstFindResponse:
    """在 Python 文件中查找指定的代码元素（函数、类、方法、变量），返回精确的行号和上下文。"""
    return _ast_find(file_path, target_type, name)


class AstRenameInput(BaseModel):
    file_path: str = Field(description="要编辑的 Python 文件路径")
    old_name: str = Field(description="原名称")
    new_name: str = Field(description="新名称")
    scope: str = Field(default="all", description="范围: all(整个文件), function:函数名(指定函数内)")


@tool("ast_rename", args_schema=AstRenameInput)
def ast_rename(file_path: str, old_name: str, new_name: str, scope: str = "all") -> AstEditResponse:
    """AST 级别重命名：在 Python 文件中安全地重命名函数名、类名、变量名。
    比字符串替换更安全，只修改同作用域内的同名标识符。"""
    return _ast_rename(file_path, old_name, new_name, scope)


class AstAddParamInput(BaseModel):
    file_path: str = Field(description="要编辑的 Python 文件路径")
    func_name: str = Field(description="函数名")
    param_name: str = Field(description="新参数名")
    default_value: Optional[str] = Field(default=None, description="默认值（如 None, 'default'），为 None 则无默认值")
    position: int = Field(default=-1, description="插入位置（-1 末尾，0 self 后面）")


@tool("ast_add_param", args_schema=AstAddParamInput)
def ast_add_param(file_path: str, func_name: str, param_name: str,
                  default_value: Optional[str] = None, position: int = -1) -> AstEditResponse:
    """AST 级别操作：为 Python 函数添加参数。自动处理 self/cls 位置和默认值语法。"""
    return _ast_add_param(file_path, func_name, param_name, default_value, position)


class AstAddMethodInput(BaseModel):
    file_path: str = Field(description="要编辑的 Python 文件路径")
    class_name: str = Field(description="类名")
    method_code: str = Field(description="完整的方法代码（def 语句）")
    position: int = Field(default=-1, description="插入位置（-1 末尾，0 开头）")


@tool("ast_add_method", args_schema=AstAddMethodInput)
def ast_add_method(file_path: str, class_name: str, method_code: str,
                   position: int = -1) -> AstEditResponse:
    """AST 级别操作：在 Python 类中添加方法。自动处理缩进。"""
    return _ast_add_method(file_path, class_name, method_code, position)


class AstAddImportInput(BaseModel):
    file_path: str = Field(description="要编辑的 Python 文件路径")
    import_statement: str = Field(description="import 语句，如 'from os.path import join'")


@tool("ast_add_import", args_schema=AstAddImportInput)
def ast_add_import(file_path: str, import_statement: str) -> AstEditResponse:
    """AST 级别操作：在 Python 文件顶部添加 import 语句。自动放在现有 import 之后，避免重复。"""
    return _ast_add_import(file_path, import_statement)


# 所有 AST 工具
ast_tools = [ast_info, ast_find, ast_rename, ast_add_param, ast_add_method, ast_add_import]
