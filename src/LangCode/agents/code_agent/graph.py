"""CodeAgent：专注于代码生成、文件编辑、调试

图结构：agent → tools → verify → (pass: END | fail: agent)
验证节点在代码修改后自动运行：语法检查 + 导入检查 + 测试运行
形成 write→verify→fix 闭环
"""

import os
import subprocess
import sys
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.routing import should_use_tools
from LangCode.shared.logger import get_logger
from LangCode.agents.base import BaseAgent

log = get_logger("agents.code")

CODE_AGENT_PROMPT = """你是一个专业的代码工程师 Agent。

## 职责
- 编写、修改、调试代码
- 创建和编辑文件
- 运行验证（如果适用）

## 工作方式
1. 先理解需求和上下文（读取相关文件）
2. 编写或修改代码
3. 验证节点自动运行：语法检查 → 导入检查 → 相关测试
4. 如有错误，立即修复

## 可用工具
- `read_file` — 读取文件内容
- `write_file` — 写入文件
- `edit_file` — 精确编辑文件
- `search_files` — 搜索文件
- `execute_shell` — 执行 shell 命令
- `run_python` — 执行 Python 代码
- `git_status` — 查看工作区状态
- `git_diff` — 查看变更差异

## 行为准则
- 修改代码前必须先阅读原文件
- 编辑时使用 edit_file 进行精确修改
- 写入新文件时使用 write_file
- **关键**：验证节点会自动检查语法错误和导入问题
- 如果验证报告错误，必须立即修复，不要忽略
"""


def _extract_modified_python_files(state: LCState) -> list[str]:
    """从最近的工具调用结果中提取被修改的 Python 文件路径"""
    files = set()
    for msg in reversed(state["messages"][-10:]):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                if name in ("write_file", "edit_file") and "file_path" in args:
                    path = args["file_path"]
                    if path.endswith(".py"):
                        files.add(path)
    return list(files)


def _find_test_files(modified_files: list[str]) -> list[str]:
    """为修改的文件查找对应的测试文件"""
    test_files = []
    for fpath in modified_files:
        basename = os.path.basename(fpath)
        dirname = os.path.dirname(fpath)
        # 常见的测试文件命名约定
        candidates = [
            os.path.join(dirname, f"test_{basename}"),
            os.path.join(dirname, f"{basename.replace('.py', '_test.py')}"),
            os.path.join(dirname, "tests", f"test_{basename}"),
        ]
        # 也检查 tests/ 目录
        if "src" in dirname:
            test_dir = dirname.replace("src", "tests")
            candidates.append(os.path.join(test_dir, f"test_{basename}"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                test_files.append(candidate)
                break
    return test_files


def _run_syntax_check(files: list[str]) -> list[str]:
    """运行 py_compile 语法检查"""
    errors = []
    for fpath in files:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", fpath],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"语法错误: {fpath}"
                errors.append(f"[语法] {error_msg}")
                log.warning("syntax check 失败: %s", fpath)
            else:
                log.debug("syntax check 通过: %s", fpath)
        except FileNotFoundError:
            log.warning("syntax check: 文件不存在 %s", fpath)
        except subprocess.TimeoutExpired:
            errors.append(f"[语法] 验证超时: {fpath}")
    return errors


def _run_import_check(files: list[str]) -> list[str]:
    """尝试导入修改的模块，检查导入链是否完整"""
    errors = []
    for fpath in files:
        # 将文件路径转为模块名
        mod_path = fpath.replace("/", ".").replace("\\", ".").replace(".py", "")
        if mod_path.startswith("src."):
            mod_path = mod_path[4:]
        try:
            result = subprocess.run(
                [sys.executable, "-c", f"import {mod_path.split('.')[-1]}"],
                capture_output=True, text=True, timeout=10,
                cwd=os.path.dirname(fpath) or ".",
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                    errors.append(f"[导入] {fpath}: {stderr.splitlines()[-1] if stderr else '导入失败'}")
                    log.warning("import check 失败: %s", fpath)
        except Exception:
            pass  # 导入检查是尽力而为，不阻塞
    return errors


def _run_tests(test_files: list[str]) -> list[str]:
    """运行相关的测试文件"""
    if not test_files:
        return []
    errors = []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"] + test_files + ["-x", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            # 提取失败摘要（最后几行）
            stderr_lines = result.stdout.strip().splitlines()
            failure_summary = "\n".join(stderr_lines[-10:]) if stderr_lines else "测试失败"
            errors.append(f"[测试]\n{failure_summary}")
            log.warning("tests 失败: %s", test_files)
        else:
            log.debug("tests 通过: %s", test_files)
    except subprocess.TimeoutExpired:
        errors.append("[测试] 测试执行超时（60s）")
    except FileNotFoundError:
        log.debug("pytest 不可用，跳过测试")
    return errors


def _verify_node(state: LCState) -> dict:
    """验证节点：语法检查 → 导入检查 → 测试运行"""
    files = _extract_modified_python_files(state)
    if not files:
        log.debug("verify: 无 Python 文件被修改，跳过验证")
        return {}

    log.info("verify: 验证 %d 个 Python 文件: %s", len(files), files)

    all_errors = []
    all_errors.extend(_run_syntax_check(files))
    all_errors.extend(_run_import_check(files))

    test_files = _find_test_files(files)
    if test_files:
        log.info("verify: 找到 %d 个测试文件: %s", len(test_files), test_files)
        all_errors.extend(_run_tests(test_files))

    if all_errors:
        error_summary = "\n".join(all_errors)
        return {"messages": [SystemMessage(
            content=f"[代码验证失败]\n以下问题需要修复：\n{error_summary}\n\n请分析错误并立即修复。"
        )]}

    log.info("verify: 所有验证通过")
    return {}


def _verify_routing(state: LCState) -> Literal["agent", "__end__"]:
    """验证后路由：如果有错误，回到 agent 修复；否则结束"""
    last_message = state["messages"][-1]
    if isinstance(last_message, SystemMessage) and "代码验证失败" in (last_message.content or ""):
        return "agent"
    return END


def _tools_routing(state: LCState) -> Literal["verify", "__end__"]:
    """工具执行后路由：检查 LLM 是否还要继续调用工具"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "verify"
    return END


class CodeAgent(BaseAgent):
    name = "code"
    description = "代码工程师：编写、修改、调试代码，创建和编辑文件"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def build_graph(self) -> CompiledStateGraph:
        """CodeAgent 专用图：agent → tools → verify → (pass: END | fail: agent)"""
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)
        builder.add_node("verify", _verify_node)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", should_use_tools)
        builder.add_edge("tools", "verify")
        builder.add_conditional_edges("verify", _verify_routing)

        return builder.compile(checkpointer=self.checkpoint)

    def get_system_prompt(self) -> str:
        return CODE_AGENT_PROMPT
