# 主智能体，目前先实现工具调用功能

# 朴素的多轮对话智能体，不制定计划，允许调用工具，后续会增加更多功能，采用经典ReAct循环

from typing import List, Dict, Any, Optional, Iterator, AsyncIterator

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from LangCode.shared.state import LCState





class SupervisorAgent:
    def __init__(self, llm: ChatOpenAI, sys_tools: list[BaseTool]) -> None:
        super().__init__(name="SupervisorAgent")
        self.tools = sys_tools
        self.llm = llm.bind_tools(self.tools)
        self.graph = self.make_graph()

    def make_graph(self):
        builder = StateGraph(LCState)  # type: ignore[arg-type]
        tool_node = ToolNode(tools=self.tools)

        builder.add_edge(START, END)

        builder.add_node("tools", tool_node)
        graph = builder.compile()
        return graph

    def get_graph(self):
        return self.graph

