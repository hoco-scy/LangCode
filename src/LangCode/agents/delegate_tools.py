"""多 Agent 委托工具 — Command Handoff 模式

每个工具返回 Command(goto="{name}_agent")，由 LangGraph 将控制流
转移到 Supervisor 图中的子 Agent 节点。子 Agent 完成后通过图的无条件
边回到 Supervisor 的 agent 节点。
"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolArg
from pydantic import BaseModel, Field
from langgraph.types import Command

from LangCode.shared.logger import get_logger

log = get_logger("agents.delegate")


class DelegateInput(BaseModel):
    task: str = Field(description="要委派给子 Agent 的具体任务描述")
    context: str = Field(default="", description="额外的上下文信息")


def _make_handoff_tool(agent_name: str, agents: dict):
    """创建 handoff 工具：返回 Command 跳转到子 Agent 节点。"""
    agent = agents[agent_name]
    tool_name = f"delegate_to_{agent_name}"
    tool_desc = f"将任务委派给{agent.description}执行。适用于需要{agent.description}的场景。"

    @tool(tool_name, args_schema=DelegateInput, description=tool_desc)
    def handoff(
        task: str,
        context: str = "",
        tool_call_id: Annotated[str, InjectedToolArg] = "",
    ) -> Command:
        """将任务委派给指定的专业 Agent 执行。"""
        log.info("handoff → %s: %s", agent_name, task[:100])

        sys_prompt = agent.get_system_prompt()
        if context:
            sys_prompt += f"\n\n## 额外上下文\n{context}"

        return Command(
            goto=f"{agent_name}_agent",
            update={"messages": [
                ToolMessage(content=f"[已委托给 {agent_name}]", tool_call_id=tool_call_id),
                SystemMessage(content=sys_prompt),
                HumanMessage(content=task),
            ]},
        )

    return handoff


def create_delegate_tools(sub_agents: dict) -> list:
    """创建所有委托工具

    Args:
        sub_agents: {"code": CodeAgent, "research": ResearchAgent, "review": ReviewAgent}
    """
    return [
        _make_handoff_tool("code", sub_agents),
        _make_handoff_tool("research", sub_agents),
        _make_handoff_tool("review", sub_agents),
    ]
