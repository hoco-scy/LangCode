# 主智能体 —— 中枢路由架构
#
# 图结构（回环模式）：
#   START → supervisor(中枢路由) → conditional:
#     "react"    → agent
#     "plan"     → planner → step_inject → agent → ... → reflector → supervisor
#     "code"     → code_agent → supervisor
#     "research" → research_agent → supervisor
#     "review"   → review_agent → supervisor
#     "end"      → END
#
# 关键设计：agent 节点被 react 和 plan 路径共享。
# agent 后的路由由统一的 _agent_routing 函数处理：
#   - 有 tool_calls → mode_tools
#   - 在 plan 执行中 + 无 tool_calls → reflector
#   - 不在 plan 执行中 + 无 tool_calls → supervisor
#
# 每条子路径完成后回到 supervisor，由 supervisor 决定下一步。
# 最大迭代保护：超过 MAX_SUPERVISOR_ITERATIONS 强制结束。

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
    supervisor_node, supervisor_routing, MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.planning.schema import Plan

log = get_logger("supervisor.graph")


# ============================================================
#  辅助节点函数
# ============================================================

def _increment_retry(state: LCState) -> dict:
    """工具执行后递增重试计数"""
    return {"tool_retry_count": state.get("tool_retry_count", 0) + 1}


def _step_inject(state: LCState) -> dict:
    """Plan 路径：注入当前步骤执行提示到消息流"""
    plan_data = state.get("current_plan")
    if not plan_data:
        log.warning("step_inject: 无计划数据")
        return {}

    try:
        plan = Plan(**plan_data)
    except Exception:
        log.warning("step_inject: 计划数据解析失败")
        return {}

    current = plan.current()
    if not current:
        log.info("step_inject: 所有步骤已完成")
        return {}

    log.info("注入步骤 %d: %s", current.step_id, current.description)
    current.status = "in_progress"

    prompt = f"""你正在执行一个多步骤任务计划中的某一步。

当前计划：
{plan.to_display()}

你当前需要执行第 {current.step_id} 步：{current.description}

请使用可用工具完成这一步。完成后，用简洁的文字总结执行结果。
如果这一步不需要工具调用（如分析、总结），直接回复即可。"""

    return {
        "messages": [SystemMessage(content=prompt)],
        "current_plan": plan.model_dump(),
        "plan_step_index": current.step_id - 1,
    }


# ============================================================
#  统一路由函数
# ============================================================

def _agent_routing(state: LCState) -> Literal["mode_tools", "reflector", "__end__"]:
    """agent 后的统一路由：根据 state 判断下一步

    - 有 tool_calls → mode_tools（继续 ReAct 循环）
    - 在 plan 执行流程中 + 无 tool_calls → reflector（评估步骤结果）
    - 否则 → END（react 路径完成，直接返回结果给用户）
    """
    last_message = state["messages"][-1]
    has_tool_calls = isinstance(last_message, AIMessage) and last_message.tool_calls

    if has_tool_calls:
        return "mode_tools"

    # 检查是否在 plan 执行流程中（步骤正在执行）
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active" and plan.current() and plan.current().status == "in_progress":
                return "reflector"
        except Exception:
            pass

    # react 路径完成 → 直接结束，不回 supervisor
    return END


def _after_tools(state: LCState) -> Literal["agent", "supervisor"]:
    """retry_tracker 后路由：回到 agent 继续循环，或回 supervisor（迭代保护）"""
    iterations = state.get("supervisor_iterations", 0)
    if iterations > MAX_SUPERVISOR_ITERATIONS:
        return "supervisor"

    return "agent"


def _plan_ready(state: LCState) -> Literal["step_inject", "supervisor"]:
    """planner 后路由：计划就绪 → step_inject，失败/空 → supervisor"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return "supervisor"
    try:
        plan = Plan(**plan_data)
        if plan.status == "active" and plan.current():
            return "step_inject"
    except Exception:
        pass
    return "supervisor"


def _reflect_done(state: LCState) -> Literal["step_inject", "supervisor"]:
    """reflector 后路由：计划有更多步骤 → step_inject，完成/放弃 → supervisor"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return "supervisor"
    try:
        plan = Plan(**plan_data)
    except Exception:
        return "supervisor"

    if plan.status in ("completed", "abandoned"):
        return "supervisor"

    if plan.reflection and "需要调整" in (plan.reflection or ""):
        return "supervisor"

    current = plan.current()
    if current and current.status in ("pending", "in_progress"):
        return "step_inject"

    return "supervisor"


# ============================================================
#  SupervisorAgent
# ============================================================

class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "主控 Agent：中枢路由编排多 Agent 协作，支持 ReAct + Plan-and-Execute"

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
        """构建中枢路由架构图"""
        from LangCode.planning.planner import create_plan_node
        from LangCode.planning.reflector import reflect_node

        builder = StateGraph(LCState)
        mode_tool_node = ModeAwareToolNode(tools=self.tools)

        # === 中枢路由节点 ===
        builder.add_node("supervisor", lambda state: supervisor_node(state, self.llm))

        # === 共享节点 ===
        builder.add_node("agent", self._call_llm)
        builder.add_node("mode_tools", mode_tool_node)
        builder.add_node("retry_tracker", _increment_retry)

        # === Plan 路径专用节点 ===
        builder.add_node("planner", lambda state: create_plan_node(state, self.llm))
        builder.add_node("step_inject", _step_inject)
        builder.add_node("reflector", lambda state: reflect_node(state, self.llm))

        # === 子 Agent 节点 ===
        for name, agent in self.sub_agents.items():
            builder.add_node(f"{name}_agent", agent.get_graph())

        # === 图连接 ===

        # 入口
        builder.add_edge(START, "supervisor")

        # supervisor 条件路由（动态构建路由映射，仅包含存在的子Agent节点）
        supervisor_routes = {
            "react": "agent",
            "plan": "planner",
            "end": END,
        }
        for name in self.sub_agents:
            supervisor_routes[name] = f"{name}_agent"

        # supervisor_routing 需要根据可用子Agent动态返回有效路由
        available_sub_agents = set(self.sub_agents.keys())
        def _dynamic_supervisor_routing(state: LCState) -> str:
            route = supervisor_routing(state)
            # 如果路由指向不可用的子Agent，回退到 react
            if route in available_sub_agents:
                return route
            if route in supervisor_routes:
                return route
            return "react"

        builder.add_conditional_edges("supervisor", _dynamic_supervisor_routing, supervisor_routes)

        # --- agent 统一路由 ---
        builder.add_conditional_edges("agent", _agent_routing)

        # --- 工具执行 → retry → agent ---
        builder.add_edge("mode_tools", "retry_tracker")
        builder.add_conditional_edges("retry_tracker", _after_tools)

        # --- Plan 路径 ---
        builder.add_conditional_edges("planner", _plan_ready)
        builder.add_edge("step_inject", "agent")
        builder.add_conditional_edges("reflector", _reflect_done)

        # --- 子 Agent 回环 ---
        for name in self.sub_agents:
            builder.add_edge(f"{name}_agent", "supervisor")

        return builder.compile(checkpointer=self.checkpoint)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_system_prompt(self) -> str:
        return AGENT_PROMPT
