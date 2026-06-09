"""Agent 基类：所有专业 Agent 的公共抽象"""

from abc import ABC, abstractmethod
from typing import Optional

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger

log = get_logger("agents.base")


class BaseAgent(ABC):
    """Agent 基类"""

    name: str = "base"
    description: str = "基础 Agent"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        self.llm = llm
        self.checkpoint = checkpoint
        self.tools = tools
        self.bound_llm = llm.bind_tools(tools)
        self.graph = self.build_graph()

    @abstractmethod
    def build_graph(self) -> CompiledStateGraph:
        """构建 Agent 的执行图"""
        ...

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
