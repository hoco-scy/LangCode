"""auto_verify — 代码修改后自动验证节点。

LangCode 差异化功能：
Claude Code 的 Verification Agent 是独立对抗性 Agent（独立子图、后台运行）。
LangCode 的 auto_verify 是内联的建设性检查（主图节点、同步执行）。

这是"硬保证"——不是靠提示词请求 LLM "请检查你的代码"，而是强制执行验证。

四层验证：
  1. py_compile 语法检查
  2. import 导入检查（动态 import 测试）
  3. ruff linter（可选，如果已安装）
  4. pytest 测试（可选，如果找到相关测试文件）
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("agents.verify")


def auto_verify(state: dict) -> dict:
    """auto_verify 节点：代码修改后自动验证。

    从 state["messages"] 中提取最近的 write_file/edit_file/ast_* 调用，
    对涉及的 Python 文件执行四层验证。

    Returns:
        - 无错误: {"verify_errors": None}
        - 有错误: {"verify_errors": [...], "messages": [SystemMessage(...)]}
    """
    files = _extract_modified_python_files(state)
    if not files:
        log.debug("auto_verify: 无 Python 文件被修改，跳过")
        return {"verify_errors": None}

    log.info("auto_verify: 验证 %d 个文件: %s", len(files), files)

    all_errors: list[str] = []
    all_errors.extend(_syntax_check(files))
    all_errors.extend(_import_check(files))
    all_errors.extend(_ruff_check(files))

    test_files = _find_test_files(files)
    if test_files:
        log.info("auto_verify: 找到 %d 个测试文件", len(test_files))
        all_errors.extend(_run_tests(test_files))

    if all_errors:
        from langchain_core.messages import SystemMessage
        error_summary = "\n".join(all_errors)
        log.warning("auto_verify: %d 个错误", len(all_errors))
        return {
            "messages": [SystemMessage(
                content=(
                    f"[自动验证失败] 以下问题需要修复：\n{error_summary}\n\n"
                    "请分析错误并立即修复。不要继续下一步。"
                )
            )],
            "verify_errors": all_errors,
        }

    log.info("auto_verify: 所有验证通过")
    return {"verify_errors": None}


def after_verify_routing(state: dict) -> str:
    """auto_verify 后路由：有错误 → "agent"（修复），无错误 → "router"（继续）"""
    if state.get("verify_errors"):
        return "agent"
    return "router"


def _extract_modified_python_files(state: dict) -> list[str]:
    """从最近一轮 AI 工具调用中提取被修改的 Python 文件路径。

    只检查最近一条 AIMessage，避免对同一文件重复验证。
    """
    from langchain_core.messages import AIMessage

    files: set[str] = set()
    messages = state.get("messages", [])

    # 只检查最近一条含 tool_calls 的 AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                if name in ("write_file", "edit_file", "ast_rename",
                            "ast_add_param", "ast_add_method", "ast_add_import"):
                    path = args.get("file_path", "")
                    if path and path.endswith(".py") and os.path.isfile(path):
                        files.add(os.path.abspath(path))
            break  # 只检查最近一条

    return list(files)


def _syntax_check(files: list[str]) -> list[str]:
    """py_compile 语法检查。"""
    errors: list[str] = []
    for fpath in files:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", fpath],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"语法错误: {fpath}"
                errors.append(f"[语法] {error_msg}")
                log.warning("语法检查失败: %s", fpath)
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            errors.append(f"[语法] 验证超时: {fpath}")
    return errors


def _import_check(files: list[str]) -> list[str]:
    """动态 import 检查。仅对 Python 包内的文件执行（有 __init__.py 的目录）。"""
    errors: list[str] = []
    for fpath in files:
        # 跳过不在 Python 包中的独立脚本
        parent = os.path.dirname(fpath)
        if not os.path.isfile(os.path.join(parent, "__init__.py")):
            continue
        mod_path = fpath.replace("/", ".").replace("\\", ".").replace(".py", "")
        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 f"import sys; sys.path.insert(0, '.'); __import__('{mod_path}')"],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                    errors.append(f"[导入] {fpath}: {stderr.splitlines()[-1] if stderr else '导入失败'}")
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
    return errors


def _ruff_check(files: list[str]) -> list[str]:
    """ruff linter 检查（可选，如果已安装）。"""
    errors: list[str] = []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check"] + files,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode != 0 and result.stdout.strip():
            errors.append(f"[ruff] {result.stdout.strip()[-500:]}")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    return errors


def _find_test_files(modified_files: list[str]) -> list[str]:
    """为修改的文件查找对应的测试文件。"""
    test_files: list[str] = []
    for fpath in modified_files:
        basename = os.path.basename(fpath)
        dirname = os.path.dirname(fpath)
        candidates = [
            os.path.join(dirname, f"test_{basename}"),
            os.path.join(dirname, f"{basename.replace('.py', '_test.py')}"),
            os.path.join(dirname, "tests", f"test_{basename}"),
        ]
        if "src" in dirname:
            test_dir = dirname.replace("src", "tests")
            candidates.append(os.path.join(test_dir, f"test_{basename}"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                test_files.append(candidate)
                break
    return test_files


def _run_tests(test_files: list[str]) -> list[str]:
    """运行相关测试。"""
    if not test_files:
        return []
    errors: list[str] = []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"] + test_files + ["-x", "-q", "--tb=short"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        if result.returncode != 0:
            stdout_lines = result.stdout.strip().splitlines()
            failure_summary = "\n".join(stdout_lines[-10:]) if stdout_lines else "测试失败"
            errors.append(f"[测试]\n{failure_summary}")
    except subprocess.TimeoutExpired:
        errors.append("[测试] 测试执行超时（60s）")
    except FileNotFoundError:
        pass
    return errors
