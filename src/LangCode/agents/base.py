"""Agent 基类：所有专业 Agent 的公共抽象"""

from abc import ABC, abstractmethod
from typing import Optional

from langchain_core.messages import AIMessage
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

log = get_logger("agents.base")


class BaseAgent(ABC):
    """Agent 基类：提供默认的 ReAct 图实现，子类可覆盖 build_graph 定制流程"""

    name: str = "base"
    description: str = "基础 Agent"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        self.llm = llm
        self.checkpoint = checkpoint
        self.tools = tools
        self.bound_llm = llm.bind_tools(tools)
        self.graph = self.build_graph()

    def _call_llm(self, state: LCState) -> dict:
        """默认 LLM 调用节点：直接调用绑定工具的 LLM"""
        response = self.bound_llm.invoke(state["messages"])
        return {"messages": [response]}

    def build_graph(self) -> CompiledStateGraph:
        """默认构建 ReAct 循环图。子类可覆盖以定制特殊流程。"""
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", should_use_tools)
        builder.add_edge("tools", "agent")

        return builder.compile(checkpointer=self.checkpoint)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """获取 Agent 的系统提示"""
        ...

    def get_tool_descriptions(self) -> str:
        """获取工具描述摘要，供 Supervisor 路由参考"""
        lines = []
        for t in self.tools:
            desc = t.description or "无描述"
            lines.append(f"- {t.name}: {desc[:80]}")
        return "\n".join(lines)

    def get_graph(self) -> CompiledStateGraph:
        return self.graph
