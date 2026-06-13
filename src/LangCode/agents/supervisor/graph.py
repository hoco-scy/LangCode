# 主智能体 —— Plan-Execute + ReAct 混合范式
#
# 业界公认最实用的模式："外层 Plan-Execute，内层 ReAct"
# - Plan-Execute 负责高层次任务规划（"做什么"）
# - 每个子任务由 ReAct 执行器完成（"怎么做"）
#
# 图结构（仅 4 个核心节点）：
#   START → agent → conditional:
#     tool_calls → mode_tools → retry_tracker → agent (ReAct 循环)
#     plan_steps → plan_create → step_inject → agent (Plan 执行)
#     delegate   → delegate_inject → 子Agent → END
#     否则 → END
#
#   Plan 执行内循环：
#     step_inject → agent → mode_tools → agent → ... → reflector
#     reflector → step_inject (下一步) 或 END (完成)
#
# agent 既做初始分析，也做步骤执行（角色由上下文决定）。

from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.shared.mode_tools import ModeAwareToolNode
from LangCode.agents.base import BaseAgent
from LangCode.agents.supervisor.prompts import AGENT_PROMPT
from LangCode.agents.supervisor.router import (
    extract_decision_from_agent, plan_create_from_agent, should_create_plan,
    delegate_routing, MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.planning.schema import Plan

log = get_logger("supervisor.graph")


# ============================================================
#  节点函数
# ============================================================

def _increment_retry(state: LCState) -> dict:
    return {"tool_retry_count": state.get("tool_retry_count", 0) + 1}


def _extract_decision_node(state: LCState) -> dict:
    """从 agent 响应中提取路由决策"""
    return extract_decision_from_agent(state)


def _step_inject(state: LCState) -> dict:
    """注入当前步骤的执行提示"""
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

    log.info("执行步骤 %d/%d: %s", current.step_id, len(plan.steps), current.description)
    current.status = "in_progress"

    prompt = f"""你正在执行计划的第 {current.step_id}/{len(plan.steps)} 步。

当前计划：
{plan.to_display()}

请使用工具完成这一步：{current.description}
完成后用简洁文字总结结果。不需要工具时直接回复。"""

    return {
        "messages": [SystemMessage(content=prompt)],
        "current_plan": plan.model_dump(),
        "plan_step_index": current.step_id - 1,
    }


def _delegate_inject(state: LCState) -> dict:
    """为子 Agent 注入任务上下文"""
    task = state.get("task_description", "")
    if task:
        return {"messages": [HumanMessage(content=task)]}
    return {}


# ============================================================
#  路由函数
# ============================================================

def _unified_agent_routing(state: LCState) -> str:
    """agent 后的统一路由（处理所有场景）

    优先级：
    1. tool_calls → mode_tools（ReAct 内循环）
    2. plan_steps → plan_create（需要创建计划）
    3. delegate 标签 → delegate（委派给子Agent）
    4. 在 plan 执行中 → reflector（评估步骤）
    5. 否则 → END（直接回复）
    """
    last_message = state["messages"][-1]
    has_tool_calls = isinstance(last_message, AIMessage) and last_message.tool_calls

    # 1. ReAct 循环
    if has_tool_calls:
        return "mode_tools"

    # 2. 需要创建计划
    route = state.get("route", "")
    if route == "plan" and state.get("plan_steps"):
        return "plan_create"

    # 3. 委派给子 Agent
    if route in ("code", "research", "review"):
        return "delegate"

    # 4. 在 plan 执行流程中 → reflector
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active" and plan.current() and plan.current().status == "in_progress":
                return "reflector"
        except Exception:
            pass

    # 5. 直接回复
    return END


def _after_tools_routing(state: LCState) -> Literal["agent", "reflector"]:
    """mode_tools/retry_tracker 后路由

    - 在 plan 执行中 → reflector（步骤的工具调用完成，评估结果）
    - 否则 → agent（ReAct 循环继续）
    """
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active" and plan.current() and plan.current().status == "in_progress":
                return "reflector"
        except Exception:
            pass
    return "agent"


def _plan_create_routing(state: LCState) -> Literal["step_inject", "__end__"]:
    """plan_create 后路由：计划就绪 → step_inject"""
    plan_data = state.get("current_plan")
    if plan_data:
        try:
            plan = Plan(**plan_data)
            if plan.status == "active" and plan.current():
                return "step_inject"
        except Exception:
            pass
    return END


def _reflect_routing(state: LCState) -> Literal["step_inject", "__end__"]:
    """reflector 后路由：更多步骤 → step_inject，完成 → END"""
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
    if current and current.status in ("pending",):
        return "step_inject"

    return END


# ============================================================
#  SupervisorAgent
# ============================================================

class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "主控 Agent：Plan-Execute + ReAct 混合范式"

    def __init__(self, llm: ChatOpenAI, sys_checkpoint: Checkpointer, sys_tools: list[BaseTool],
                 sub_agents: dict = None):
        self.sub_agents = sub_agents or {}
        super().__init__(llm, sys_checkpoint, sys_tools)

    def _inject_context(self, state: LCState) -> list:
        """注入当前计划摘要"""
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
        """构建混合范式图：4 个核心节点"""
        builder = StateGraph(LCState)
        mode_tool_node = ModeAwareToolNode(tools=self.tools)

        # === 4 个核心节点 ===
        builder.add_node("agent", self._call_llm)
        builder.add_node("mode_tools", mode_tool_node)
        builder.add_node("retry_tracker", _increment_retry)
        builder.add_node("step_inject", _step_inject)

        # 路由辅助节点
        builder.add_node("extract_decision", _extract_decision_node)
        builder.add_node("plan_create", plan_create_from_agent)

        # reflector
        builder.add_node("reflector", lambda state: self._reflect_node(state))

        # === 图连接 ===

        # 入口
        builder.add_edge(START, "agent")

        # agent → extract_decision（提取路由信号）
        builder.add_edge("agent", "extract_decision")

        # extract_decision → 统一路由
        delegate_targets = {f"{n}_agent": f"{n}_agent" for n in self.sub_agents}
        builder.add_conditional_edges("extract_decision", _unified_agent_routing, {
            "mode_tools": "mode_tools",
            "plan_create": "plan_create",
            "delegate": "delegate_inject" if self.sub_agents else END,
            "reflector": "reflector",
            "__end__": END,
            **{k: k for k in delegate_targets},
        })

        # ReAct 内循环
        builder.add_edge("mode_tools", "retry_tracker")
        builder.add_conditional_edges("retry_tracker", _after_tools_routing, {
            "agent": "agent",
            "reflector": "reflector",
        })

        # Plan 创建 → 执行
        builder.add_conditional_edges("plan_create", _plan_create_routing, {
            "step_inject": "step_inject",
            "__end__": END,
        })
        builder.add_edge("step_inject", "agent")

        # Reflector → 下一步或结束
        builder.add_conditional_edges("reflector", _reflect_routing, {
            "step_inject": "step_inject",
            "__end__": END,
        })

        # Delegate 路径（仅在有子 Agent 时）
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
