# 主智能体 —— 经典 ReAct 循环
# 思考(Think) → 行动(Act) → 观察(Observe) → 循环，直到模型认为可以直接回复用户

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
from LangCode.agents.supervisor.prompts import *

log = get_logger("supervisor.graph")


def _call_llm(state: LCState, llm: ChatOpenAI) -> dict:
    """ReAct 的 Think 步骤：调用 LLM，模型自行决定是调用工具还是直接回复"""
    msg_count = len(state["messages"])
    log.debug("调用 LLM，当前消息数: %d", msg_count)
    response = llm.invoke(state["messages"])
    if response.tool_calls:
        log.info("LLM 请求工具调用: %s", [tc["name"] for tc in response.tool_calls])
    else:
        content_preview = (response.content or "")[:120]
        log.debug("LLM 直接回复: %s...", content_preview)
    return {"messages": [response]}


def _should_use_tools(state: LCState) -> Literal["tools", "__end__"]:
    """ReAct 的路由：检查 LLM 是否产生了工具调用"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        log.debug("路由 -> tools")
        return "tools"
    log.debug("路由 -> END")
    return END


class SupervisorAgent:
    def __init__(self, llm: ChatOpenAI, sys_checkpoint: Checkpointer, sys_tools: list[BaseTool]) -> None:
        self.tools = sys_tools
        self.llm = llm.bind_tools(self.tools)
        self.checkpoint = sys_checkpoint
        self.graph = self.make_graph()

    def make_graph(self) -> CompiledStateGraph:
        builder = StateGraph(LCState)  # type: ignore[arg-type]
        tool_node = ToolNode(tools=self.tools)

        # agent 节点：调用 LLM（Think）
        builder.add_node("agent", lambda state: _call_llm(state, self.llm))
        # tools 节点：执行工具调用（Act + Observe）
        builder.add_node("tools", tool_node)

        # 入口 → agent
        builder.add_edge(START, "agent")
        # agent → 条件路由：有工具调用则去 tools，否则结束
        builder.add_conditional_edges("agent", _should_use_tools)
        # tools 执行完 → 回到 agent（循环）
        builder.add_edge("tools", "agent")

        return builder.compile(checkpointer=self.checkpoint)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_graph(self) -> CompiledStateGraph:
        return self.graph