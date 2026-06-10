# 主智能体 —— ReAct + Plan-and-Execute 双模式编排器
# 简单任务: Think → Act → Observe 循环
# 复杂任务: Plan → Execute Step → Reflect → Next Step 循环
#
# 继承 BaseAgent 复用：上下文管理、记忆注入、重试保护。
# 通过 _inject_context() 钩子额外注入计划摘要。

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
from LangCode.shared.logger import get_logger
from LangCode.agents.base import BaseAgent
from LangCode.agents.supervisor.prompts import AGENT_PROMPT
from LangCode.planning.schema import Plan

log = get_logger("supervisor.graph")


# ============================================================
#  辅助函数
# ============================================================

def _increment_retry(state: LCState) -> dict:
    """工具执行后递增重试计数"""
    return {"tool_retry_count": state.get("tool_retry_count", 0) + 1}


def _should_plan(state: LCState) -> Literal["planner", "step_executor", "react"]:
    """路由：检查是否需要进入规划模式"""
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active":
                if plan.steps and any(s.status in ("pending", "in_progress") for s in plan.steps):
                    log.debug("路由 -> step_executor (计划已就绪)")
                    return "step_executor"
                log.debug("路由 -> planner (需要规划)")
                return "planner"
        except Exception:
            pass
    log.debug("路由 -> react (无计划)")
    return "react"


def _plan_or_end(state: LCState) -> Literal["step_executor", "__end__"]:
    """路由：计划是否还有步骤需要执行"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return END
    plan = Plan(**plan_data)
    if plan.status in ("completed", "abandoned"):
        log.info("计划已完成/放弃")
        return END
    current = plan.current()
    if current and current.status in ("pending", "in_progress"):
        return "step_executor"
    return END


def _after_step(state: LCState) -> Literal["reflector", "agent"]:
    """路由：步骤执行后，如果需要工具调用则回到 agent 的 ReAct 循环"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "agent"
    return "reflector"


# ============================================================
#  SupervisorAgent
# ============================================================

class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "主控 Agent：编排多 Agent 协作，支持 ReAct + Plan-and-Execute 双模式"

    def __init__(self, llm: ChatOpenAI, sys_checkpoint: Checkpointer, sys_tools: list[BaseTool]):
        super().__init__(llm, sys_checkpoint, sys_tools)

    def _inject_context(self, state: LCState) -> list:
        """注入当前计划摘要（在 BaseAgent 的记忆注入之后）"""
        plan_data = state.get("current_plan")
        if not plan_data or not isinstance(plan_data, dict):
            return []
        try:
            plan = Plan(**plan_data)
            if plan.status == "active":
                return [SystemMessage(
                    id="current_plan",
                    content=f"[当前执行计划]\n{plan.to_display()}"
                )]
        except Exception:
            pass
        return []

    def build_graph(self) -> CompiledStateGraph:
        """构建 Plan-and-Execute + ReAct 双模式图"""
        from LangCode.planning.planner import create_plan_node
        from LangCode.planning.executor import execute_step_node
        from LangCode.planning.reflector import reflect_node

        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        # ReAct 节点
        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)
        builder.add_node("retry_tracker", _increment_retry)

        # Plan-and-Execute 节点（lambda 捕获 self.bound_llm，因为 planning 函数需要 raw invoke）
        builder.add_node("planner", lambda state: create_plan_node(state, self.bound_llm))
        builder.add_node("step_executor", lambda state: execute_step_node(state, self.bound_llm))
        builder.add_node("reflector", lambda state: reflect_node(state, self.bound_llm))

        # 图连接
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", self._agent_routing)
        builder.add_edge("tools", "retry_tracker")
        builder.add_conditional_edges("retry_tracker", _should_plan, {
            "planner": "planner",
            "step_executor": "step_executor",
            "react": "agent",
        })
        builder.add_conditional_edges("planner", _plan_or_end)
        builder.add_conditional_edges("step_executor", _after_step)
        builder.add_edge("reflector", "step_executor")

        return builder.compile(checkpointer=self.checkpoint)

    def _agent_routing(self, state: LCState) -> Literal["tools", "__end__"]:
        """Agent 节点后路由：有工具调用 → tools，否则 → END"""
        from LangCode.shared.routing import should_use_tools
        return should_use_tools(state)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_system_prompt(self) -> str:
        return AGENT_PROMPT
