"""共享路由函数：所有 Agent 图共用的条件边判断"""

from typing import Literal
from langchain_core.messages import AIMessage
from langgraph.constants import END

from LangCode.shared.state import LCState


def should_use_tools(state: LCState) -> Literal["tools", "__end__"]:
    """检查 LLM 最新消息是否包含工具调用，决定路由到 tools 节点还是结束"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END
