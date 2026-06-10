"""AST 级别的结构化代码编辑

基于 tree-sitter 的代码分析和编辑，支持 Python 代码的结构化操作：
- 查找函数、类、方法、变量
- 重命名标识符（函数名、类名、变量名、参数名）
- 添加/删除函数参数
- 在类中添加方法
- 添加 import 语句

所有操作返回精确的行号信息，编辑基于 AST 节点位置而非字符串匹配。
"""

import os
from typing import Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

from LangCode.shared.logger import get_logger
from LangCode.shared.schemas import (
    AstInfoResponse, AstFunctionInfo, AstClassInfo,
    AstFindResponse, AstFindResult,
    AstEditResponse,
)

log = get_logger("ast_editor")

# 全局解析器（线程安全，可复用）
_parser = Parser(Language(tspython.language()))

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {".py"}


def _parse_file(file_path: str) -> tuple[bytes, Node]:
    """解析文件，返回 (源码字节, 根节点)"""
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    source_bytes = source.encode("utf-8")
    tree = _parser.parse(source_bytes)
    return source_bytes, tree.root_node


def _find_assignments(node: Node) -> list[Node]:
    """递归查找赋值节点（模块级函数，避免每次调用 ast_find 重复定义）"""
    found = []
    if node.type == "assignment":
        found.append(node)
    for child in node.children:
        found.extend(_find_assignments(child))
    return found


def _find_nodes(root: Node, node_type: str, name: Optional[str] = None) -> list[Node]:
    """递归查找指定类型和名称的节点"""
    results = []
    if root.type == node_type:
        if name is not None:
            name_node = root.child_by_field_name("name")
            if name_node and name_node.text.decode() == name:
                results.append(root)
        else:
            results.append(root)
    # 递归子节点
    for child in root.children:
        results.extend(_find_nodes(child, node_type, name))
    return results


def _find_all_identifiers(root: Node, name: str) -> list[Node]:
    """查找所有同名标识符节点（用于重命名）"""
    results = []
    if root.type == "identifier" and root.text.decode() == name:
        results.append(root)
    for child in root.children:
        results.extend(_find_all_identifiers(child, name))
    return results


def _get_function_params(func_node: Node) -> list[Node]:
    """获取函数的所有参数节点"""
    params = []
    params_node = func_node.child_by_field_name("parameters")
    if params_node:
        for child in params_node.children:
            if child.type in ("identifier", "default_parameter", "typed_parameter",
                              "list_splat_pattern", "dictionary_splat_pattern"):
                params.append(child)
    return params


def _replace_in_source(source: bytes, node: Node, new_text: str) -> bytes:
    """在源码中替换指定节点的文本"""
    start = node.start_byte
    end = node.end_byte
    return source[:start] + new_text.encode("utf-8") + source[end:]


def _insert_at_line(source: bytes, line: int, text: str, indent: int = 0) -> bytes:
    """在指定行插入文本（line 为 1-based）"""
    lines = source.split(b"\n")
    idx = line - 1  # 0-based
    prefix = b" " * indent
    new_line = prefix + text.encode("utf-8")
    lines.insert(idx, new_line)
    return b"\n".join(lines)


def _write_file(file_path: str, source: bytes):
    """将修改后的源码写回文件（强制 UTF-8 编码）"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(source.decode("utf-8"))


# ============================================================
#  公开 API
# ============================================================

def ast_info(file_path: str) -> AstInfoResponse:
    """分析文件的 AST 结构，返回函数、类、import 等信息"""
    if not os.path.isfile(file_path):
        return AstInfoResponse(success=False, error=f"文件不存在: {file_path}")
    if not any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        return AstInfoResponse(success=False, error=f"不支持的文件类型，仅支持: {SUPPORTED_EXTENSIONS}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstInfoResponse(success=False, error=f"解析失败: {e}")

    functions = []
    classes = []
    imports = []

    for child in root.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "?"
            params = _get_function_params(child)
            param_names = [p.text.decode().split(":")[0].split("=")[0].strip() for p in params]
            functions.append(AstFunctionInfo(name=name, line=child.start_point[0] + 1, params=param_names))
        elif child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "?"
            methods = []
            body = child.child_by_field_name("body")
            if body:
                for method_node in _find_nodes(body, "function_definition"):
                    mname = method_node.child_by_field_name("name")
                    methods.append(mname.text.decode() if mname else "?")
            classes.append(AstClassInfo(name=name, line=child.start_point[0] + 1, methods=methods))
        elif child.type in ("import_statement", "import_from_statement"):
            imports.append(child.text.decode().strip())

    return AstInfoResponse(
        success=True,
        file=file_path,
        functions=functions,
        classes=classes,
        imports=imports,
        total_lines=source_bytes.count(b"\n") + 1,
    )


def ast_find(file_path: str, target_type: str, name: str) -> AstFindResponse:
    """查找指定的 AST 节点

    Args:
        file_path: 文件路径
        target_type: 查找类型 - "function", "class", "method", "variable"
        name: 要查找的名称
    """
    if not os.path.isfile(file_path):
        return AstFindResponse(success=False, error=f"文件不存在: {file_path}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstFindResponse(success=False, error=f"解析失败: {e}")

    node_type_map = {
        "function": "function_definition",
        "class": "class_definition",
    }

    results = []
    if target_type in node_type_map:
        nodes = _find_nodes(root, node_type_map[target_type], name)
        for node in nodes:
            results.append(AstFindResult(
                name=name, type=target_type,
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                text_preview=node.text.decode()[:300],
            ))
    elif target_type == "method":
        for class_node in _find_nodes(root, "class_definition"):
            body = class_node.child_by_field_name("body")
            if body:
                for method_node in _find_nodes(body, "function_definition", name):
                    class_name_node = class_node.child_by_field_name("name")
                    results.append(AstFindResult(
                        name=name, type="method",
                        class_name=class_name_node.text.decode() if class_name_node else "?",
                        line=method_node.start_point[0] + 1,
                        end_line=method_node.end_point[0] + 1,
                        text_preview=method_node.text.decode()[:300],
                    ))
    elif target_type == "variable":
        for assign_node in _find_assignments(root):
            left = assign_node.child_by_field_name("left")
            if left and left.type == "identifier" and left.text.decode() == name:
                parent = assign_node.parent
                display_node = parent if parent and parent.type == "expression_statement" else assign_node
                results.append(AstFindResult(
                    name=name, type="variable",
                    line=display_node.start_point[0] + 1,
                    text_preview=display_node.text.decode()[:200],
                ))

    return AstFindResponse(
        success=True,
        file=file_path,
        query=f"{target_type} '{name}'",
        found=len(results),
        results=results,
    )


def ast_rename(file_path: str, old_name: str, new_name: str, scope: str = "all") -> AstEditResponse:
    """重命名标识符（函数名、类名、变量名、参数名）

    Args:
        file_path: 文件路径
        old_name: 原名称
        new_name: 新名称
        scope: 范围 - "all"(整个文件) 或 "function:func_name"(指定函数内)
    """
    if not os.path.isfile(file_path):
        return AstEditResponse(success=False, error=f"文件不存在: {file_path}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstEditResponse(success=False, error=f"解析失败: {e}")

    # 确定搜索范围
    if scope.startswith("function:"):
        func_name = scope.split(":", 1)[1]
        func_nodes = _find_nodes(root, "function_definition", func_name)
        if not func_nodes:
            return AstEditResponse(success=False, error=f"未找到函数 '{func_name}'")
        search_root = func_nodes[0]
    else:
        search_root = root

    identifiers = _find_all_identifiers(search_root, old_name)
    if not identifiers:
        return AstEditResponse(success=False, error=f"未找到标识符 '{old_name}'")

    # 同时重命名定义节点（function_definition 的 name 字段等）
    definition_nodes = []
    for func_node in _find_nodes(search_root, "function_definition"):
        name_node = func_node.child_by_field_name("name")
        if name_node and name_node.text.decode() == old_name:
            definition_nodes.append(name_node)
    for class_node in _find_nodes(search_root, "class_definition"):
        name_node = class_node.child_by_field_name("name")
        if name_node and name_node.text.decode() == old_name:
            definition_nodes.append(name_node)

    all_nodes = definition_nodes + identifiers
    # 去重（按字节位置）
    seen = set()
    unique_nodes = []
    for node in sorted(all_nodes, key=lambda n: n.start_byte):
        key = (node.start_byte, node.end_byte)
        if key not in seen:
            seen.add(key)
            unique_nodes.append(node)

    # 从后往前替换，避免字节偏移
    new_source = source_bytes
    for node in reversed(unique_nodes):
        new_source = _replace_in_source(new_source, node, new_name)

    _write_file(file_path, new_source)
    log.info("ast_rename: %s -> %s (%d 处修改)", old_name, new_name, len(unique_nodes))
    return AstEditResponse(
        success=True,
        message=f"已将 '{old_name}' 重命名为 '{new_name}'",
        changes=[f"行 {n.start_point[0]+1}: {old_name} -> {new_name}" for n in unique_nodes],
    )


def ast_add_param(file_path: str, func_name: str, param_name: str,
                  default_value: Optional[str] = None, position: int = -1) -> AstEditResponse:
    """为函数添加参数

    Args:
        file_path: 文件路径
        func_name: 函数名
        param_name: 新参数名
        default_value: 默认值（如 "None", "'default'"），为 None 则无默认值
        position: 插入位置（-1 表示追加到末尾，0 表示插入到 self 后面）
    """
    if not os.path.isfile(file_path):
        return AstEditResponse(success=False, error=f"文件不存在: {file_path}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstEditResponse(success=False, error=f"解析失败: {e}")

    func_nodes = _find_nodes(root, "function_definition", func_name)
    if not func_nodes:
        return AstEditResponse(success=False, error=f"未找到函数 '{func_name}'")

    func_node = func_nodes[0]
    params_node = func_node.child_by_field_name("parameters")
    if not params_node:
        return AstEditResponse(success=False, error=f"函数 '{func_name}' 没有参数列表")

    # 构造新参数文本
    param_text = param_name
    if default_value:
        param_text = f"{param_name}={default_value}"

    # 获取当前参数列表
    current_params = _get_function_params(func_node)
    if any(p.text.decode().split("=")[0].strip().split(":")[0].strip() == param_name for p in current_params):
        return AstEditResponse(success=False, error=f"参数 '{param_name}' 已存在")

    # 构造新的参数列表文本
    param_texts = [p.text.decode() for p in current_params]
    if position == -1:
        param_texts.append(param_text)
    elif position == 0 and param_texts and param_texts[0].strip() in ("self", "cls"):
        param_texts.insert(1, param_text)
    else:
        param_texts.insert(max(0, position), param_text)

    new_params_text = "(" + ", ".join(param_texts) + ")"
    new_source = _replace_in_source(source_bytes, params_node, new_params_text)
    _write_file(file_path, new_source)

    log.info("ast_add_param: %s(%s) 添加参数 %s", file_path, func_name, param_name)
    return AstEditResponse(
        success=True,
        message=f"已为函数 '{func_name}' 添加参数 '{param_name}'",
        changes=[f"函数 {func_name} 参数列表: 添加 {param_text}"],
    )


def ast_add_method(file_path: str, class_name: str, method_code: str,
                   position: int = -1) -> AstEditResponse:
    """在类中添加方法

    Args:
        file_path: 文件路径
        class_name: 类名
        method_code: 方法代码（完整的 def 语句）
        position: 插入位置（-1 追加到末尾，0 插入到开头）
    """
    if not os.path.isfile(file_path):
        return AstEditResponse(success=False, error=f"文件不存在: {file_path}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstEditResponse(success=False, error=f"解析失败: {e}")

    class_nodes = _find_nodes(root, "class_definition", class_name)
    if not class_nodes:
        return AstEditResponse(success=False, error=f"未找到类 '{class_name}'")

    class_node = class_nodes[0]
    body = class_node.child_by_field_name("body")
    if not body:
        return AstEditResponse(success=False, error=f"类 '{class_name}' 没有方法体")

    # 计算缩进（类体的缩进 + 4 空格）
    class_indent = class_node.start_point[1]
    method_indent = class_indent + 4

    # 确定插入行
    if position == -1:
        # 插入到最后一个方法之后、类体结束之后
        insert_line = body.end_point[0] + 2  # end_point[0] 为 0-based，+2 = 后一行 (1-based)
    else:
        # 插入到第一个方法之后
        insert_line = body.start_point[0] + 2  # body 开始后的第二行

    # 分行插入方法代码
    lines = method_code.strip().split("\n")
    new_source = source_bytes
    for i, line in enumerate(reversed(lines)):
        new_source = _insert_at_line(new_source, insert_line, line.strip(), method_indent)

    _write_file(file_path, new_source)
    log.info("ast_add_method: %s.%s 添加方法", class_name, method_code[:50])
    return AstEditResponse(
        success=True,
        message=f"已为类 '{class_name}' 添加方法",
        changes=[f"类 {class_name} 行 {insert_line}: 添加方法"],
    )


def ast_add_import(file_path: str, import_statement: str) -> AstEditResponse:
    """在文件顶部添加 import 语句（放在现有 import 之后）

    Args:
        file_path: 文件路径
        import_statement: import 语句，如 "from os.path import join"
    """
    if not os.path.isfile(file_path):
        return AstEditResponse(success=False, error=f"文件不存在: {file_path}")

    try:
        source_bytes, root = _parse_file(file_path)
    except Exception as e:
        return AstEditResponse(success=False, error=f"解析失败: {e}")

    # 检查是否已存在
    for child in root.children:
        if child.type in ("import_statement", "import_from_statement"):
            if child.text.decode().strip() == import_statement.strip():
                return AstEditResponse(success=False, error=f"import 已存在: {import_statement}")

    # 找到最后一个 import 语句的位置
    last_import_line = 0
    for child in root.children:
        if child.type in ("import_statement", "import_from_statement"):
            last_import_line = child.end_point[0] + 1  # 1-based

    if last_import_line == 0:
        # 没有现有 import，插入到文件开头
        insert_line = 1
    else:
        insert_line = last_import_line + 1

    new_source = _insert_at_line(source_bytes, insert_line, import_statement, indent=0)

    # 如果插入位置后面不是空行，添加一个空行
    lines = new_source.split(b"\n")
    idx = insert_line - 1  # 0-based
    if idx < len(lines) - 1 and lines[idx + 1].strip():
        lines.insert(idx + 1, b"")
        new_source = b"\n".join(lines)

    _write_file(file_path, new_source)
    log.info("ast_add_import: %s 添加 %s", file_path, import_statement)
    return AstEditResponse(
        success=True,
        message=f"已添加 import: {import_statement}",
        changes=[f"行 {insert_line}: {import_statement}"],
    )
