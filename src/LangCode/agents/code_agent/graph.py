"""CodeAgent：专注于代码生成、文件编辑、调试"""

from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.agents.base import BaseAgent

log = get_logger("agents.code")

CODE_AGENT_PROMPT = """你是一个专业的代码工程师 Agent。

## 职责
- 编写、修改、调试代码
- 创建和编辑文件
- 运行代码验证结果

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

## 行为准则
- 修改代码前必须先阅读原文件
- 编辑时使用 edit_file 进行精确修改
- 写入新文件时使用 write_file
- 完成后简要报告做了什么
"""


def _call_code_llm(state: LCState, llm: ChatOpenAI) -> dict:
    """CodeAgent 的 LLM 调用节点"""
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def _should_use_tools(state: LCState) -> Literal["tools", "__end__"]:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END


class CodeAgent(BaseAgent):
    name = "code"
    description = "代码工程师：编写、修改、调试代码，创建和编辑文件"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def build_graph(self) -> CompiledStateGraph:
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", lambda state: _call_code_llm(state, self.bound_llm))
        builder.add_node("tools", tool_node)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", _should_use_tools)
        builder.add_edge("tools", "agent")

        return builder.compile(checkpointer=self.checkpoint)

    def get_system_prompt(self) -> str:
        return CODE_AGENT_PROMPT
