# 主智能体 —— Plan-Execute + ReAct 混合范式（工具驱动路由）
#
# 核心改动：所有路由决策通过 tool calling 传递，不再解析文本信号
# - plan_create 工具 → 创建计划（替代编号列表文本解析）
# - delegate_* 工具 → 委派子Agent（替代 [route: xxx] 标签解析）
#
# 图结构（4 核心节点）：
#   START → agent → conditional:
#     tool_calls → mode_tools → process_tool_results → conditional(4-way):
#       mark_step → agent（新计划开始执行）
#       delegate_inject → 子Agent → END
#       reflector → conditional(2-way):
#         mark_step → agent
#         END
#       agent（ReAct 循环）
#     无 tool_calls → END

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.shared.mode_tools import ModeAwareToolNode
from LangCode.shared.routing import should_use_tools
from LangCode.agents.base import BaseAgent
from LangCode.agents.supervisor.prompts import AGENT_PROMPT
from LangCode.agents.supervisor.router import (
    process_tool_results, after_tools_routing, MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.planning.schema import Plan

log = get_logger("supervisor.graph")


# ============================================================
#  节点函数
# ============================================================

def _mark_step_in_progress(state: LCState) -> dict:
    """标记当前步骤为 in_progress"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return {}
    try:
        plan = Plan(**plan_data)
    except Exception:
        return {}
    current = plan.current()
    if not current:
        return {}
    if current.status == "pending":
        current.status = "in_progress"
        log.info("步骤 %d 开始执行: %s", current.step_id, current.description)
    return {"current_plan": plan.model_dump()}


def _delegate_inject(state: LCState) -> dict:
    """为子 Agent 注入任务上下文"""
    task = state.get("task_description", "")
    if task:
        return {"messages": [HumanMessage(content=task)]}
    return {}


# ============================================================
#  路由函数
# ============================================================

def _reflect_routing(state: LCState) -> str:
    """reflector 后路由：更多步骤 → mark_step → agent，完成 → END"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return END
    try:
        plan = Plan(**plan_data)
    except Exception:
        return END

    if plan.status in ("completed", "abandoned"):
        return END

    if plan.reflection and "需要调整" in (plan.reflection or ""):
        return END

    current = plan.current()
    if current and current.status == "pending":
        return "mark_step"

    return END


# ============================================================
#  SupervisorAgent
# ============================================================

class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "主控 Agent：Plan-Execute + ReAct 混合范式（工具驱动路由）"

    def __init__(self, llm: ChatOpenAI, sys_checkpoint: Checkpointer, sys_tools: list[BaseTool],
                 sub_agents: dict = None):
        self.sub_agents = sub_agents or {}
        super().__init__(llm, sys_checkpoint, sys_tools)

    def _inject_context(self, state: LCState) -> list:
        """注入计划上下文"""
        plan_data = state.get("current_plan")
        if not plan_data or not isinstance(plan_data, dict):
            return []
        try:
            plan = Plan(**plan_data)
        except Exception:
            return []

        if plan.status != "active":
            return []

        current = plan.current()
        if current and current.status == "in_progress":
            return [SystemMessage(
                id="plan_execution",
                content=f"你正在执行计划。严格按当前步骤操作，不要偏离。\n\n"
                        f"{plan.to_display()}\n\n"
                        f"专注完成第 {current.step_id} 步：{current.description}"
            )]
        elif current and current.status == "pending":
            return [SystemMessage(
                id="plan_next_step",
                content=f"计划的下一步即将开始。\n\n{plan.to_display()}"
            )]
        else:
            return [SystemMessage(
                id="plan_overview",
                content=f"[当前执行计划]\n{plan.to_display()}"
            )]

    def build_graph(self) -> CompiledStateGraph:
        """构建工具驱动路由图"""
        builder = StateGraph(LCState)
        mode_tool_node = ModeAwareToolNode(tools=self.tools)

        # === 核心节点 ===
        builder.add_node("agent", self._call_llm)
        builder.add_node("mode_tools", mode_tool_node)
        builder.add_node("process_tool_results", process_tool_results)
        builder.add_node("mark_step", _mark_step_in_progress)
        builder.add_node("reflector", lambda state: self._reflect_node(state))

        # === 图连接 ===

        # 入口
        builder.add_edge(START, "agent")

        # agent → mode_tools 或 END
        builder.add_conditional_edges("agent", should_use_tools, {
            "tools": "mode_tools",
            "__end__": END,
        })

        # mode_tools → process_tool_results（提取 plan/delegate 信号）
        builder.add_edge("mode_tools", "process_tool_results")

        # process_tool_results → 四路路由
        delegate_targets = {f"{n}_agent": f"{n}_agent" for n in self.sub_agents}
        builder.add_conditional_edges("process_tool_results", after_tools_routing, {
            "mark_step": "mark_step",
            "delegate": "delegate_inject" if self.sub_agents else END,
            "reflector": "reflector",
            "agent": "agent",
            **{k: k for k in delegate_targets},
        })

        # Plan: mark_step → agent
        builder.add_edge("mark_step", "agent")

        # Reflector → mark_step 或 END
        builder.add_conditional_edges("reflector", _reflect_routing, {
            "mark_step": "mark_step",
            "__end__": END,
        })

        # Delegate 路径
        if self.sub_agents:
            builder.add_node("delegate_inject", _delegate_inject)
            for name, agent_obj in self.sub_agents.items():
                builder.add_node(f"{name}_agent", agent_obj.get_graph())
            for name in self.sub_agents:
                builder.add_edge("delegate_inject", f"{name}_agent")
                builder.add_edge(f"{name}_agent", END)

        return builder.compile(checkpointer=self.checkpoint)

    def _reflect_node(self, state: LCState) -> dict:
        from LangCode.planning.reflector import reflect_node
        return reflect_node(state, self.llm)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_system_prompt(self) -> str:
        return AGENT_PROMPT
