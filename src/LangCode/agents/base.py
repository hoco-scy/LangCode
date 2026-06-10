"""Agent 基类：所有专业 Agent 的公共抽象

提供默认的 ReAct 图实现和共享能力：
- 上下文窗口管理（裁剪 + 摘要）
- 记忆上下文注入
- 工具重试上限提示

子类可覆盖 build_graph() 定制流程，覆盖 _call_llm() 添加额外注入。
"""

from abc import ABC, abstractmethod
from typing import Optional

from langchain_core.messages import AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.routing import should_use_tools
from LangCode.shared.context import trim_messages, summarize_old_messages
from LangCode.shared.logger import get_logger

log = get_logger("agents.base")

MAX_TOOL_RETRIES = 3


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
        """调用 LLM，包含上下文管理、记忆注入和重试保护"""
        messages = list(state["messages"])
        retry_count = state.get("tool_retry_count", 0)

        # 重试次数过多时提示
        if retry_count >= MAX_TOOL_RETRIES:
            log.warning("工具重试已达上限 (%d)", MAX_TOOL_RETRIES)
            messages.append(ToolMessage(
                content="[系统提示] 工具调用已连续失败多次，请直接基于已有信息回复用户。",
                tool_call_id="system_retry_limit"
            ))

        # 上下文窗口管理
        messages = trim_messages(messages)
        if self.llm:
            messages = summarize_old_messages(messages, self.llm)

        # 注入记忆上下文
        memory_context = state.get("memory_context", "")
        if memory_context:
            insert_idx = 0
            for i, m in enumerate(messages):
                if isinstance(m, SystemMessage):
                    insert_idx = i + 1
            messages.insert(insert_idx, SystemMessage(
                id="memory_context",
                content=f"[已知的相关记忆]\n{memory_context}"
            ))

        response = self.bound_llm.invoke(messages)
        if response.tool_calls:
            log.debug("LLM 请求工具: %s", [tc["name"] for tc in response.tool_calls])
        return {"messages": [response], "tool_retry_count": 0, "memory_context": ""}

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
