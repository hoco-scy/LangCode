"""CodeAgent：专注于代码生成、文件编辑、调试

图结构：agent → tools → verify → (pass: END | fail: agent)
验证节点在代码修改后自动运行语法检查，形成 write→verify→fix 闭环
"""

import re
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
3. 运行验证（如果适用）
4. 报告结果

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
- **关键**：写完代码后，验证节点会自动检查 Python 文件的语法错误
- 如果验证报告语法错误，立即修复
"""


def _extract_modified_python_files(state: LCState) -> list[str]:
    """从最近的工具调用结果中提取被修改的 Python 文件路径"""
    files = set()
    for msg in reversed(state["messages"][-10:]):
        # 从工具调用参数中提取文件路径
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                if name in ("write_file", "edit_file") and "file_path" in args:
                    path = args["file_path"]
                    if path.endswith(".py"):
                        files.add(path)
    return list(files)


def _verify_node(state: LCState) -> dict:
    """验证节点：对最近修改的 Python 文件运行语法检查"""
    files = _extract_modified_python_files(state)
    if not files:
        log.debug("verify: 无 Python 文件被修改，跳过验证")
        return {}

    log.info("verify: 检查 %d 个 Python 文件: %s", len(files), files)
    errors = []
    for fpath in files:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", fpath],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"语法错误: {fpath}"
                errors.append(error_msg)
                log.warning("verify 失败: %s -> %s", fpath, error_msg[:200])
            else:
                log.debug("verify 通过: %s", fpath)
        except FileNotFoundError:
            log.warning("verify: 文件不存在 %s", fpath)
        except subprocess.TimeoutExpired:
            errors.append(f"验证超时: {fpath}")

    if errors:
        error_summary = "\n".join(errors)
        return {"messages": [SystemMessage(
            content=f"[代码验证失败]\n以下 Python 文件存在语法错误，请立即修复：\n{error_summary}"
        )]}

    log.info("verify: 所有文件通过语法检查")
    return {}


def _verify_routing(state: LCState) -> Literal["agent", "__end__"]:
    """验证后路由：如果有语法错误，回到 agent 修复；否则结束"""
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
