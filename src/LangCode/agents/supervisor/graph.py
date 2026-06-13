# 主智能体 —— Agent-as-Entry 架构
#
# 图结构：
#   START → agent(唯一入口) → conditional:
#     有 tool_calls → mode_tools → retry_tracker → agent (ReAct 循环)
#     有 plan_steps → plan_create → step_inject → agent → ... → reflector → ... → END
#     有 route 标签 → delegate → 子Agent → END
#     否则 → END
#
# 核心优化：去掉了 supervisor 路由节点，agent 的第一次 LLM 调用
# 同时完成思考和路由决策，省去一次额外的 LLM 调用。
#
# 路由信号（按优先级）：
# 1. tool_calls → ReAct 循环（tools 路径）
# 2. plan_steps → Plan-and-Execute 路径
# 3. [route: code|research|review] 标签 → Delegate 路径
# 4. 无以上信号 → END（直接回复用户）

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
#  辅助节点函数
# ============================================================

def _increment_retry(state: LCState) -> dict:
    """工具执行后递增重试计数"""
    return {"tool_retry_count": state.get("tool_retry_count", 0) + 1}


def _extract_decision_node(state: LCState) -> dict:
    """路由提取节点：从 agent 响应中提取路由决策，写入 state"""
    updates = extract_decision_from_agent(state)
    return updates


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


def _delegate_inject(state: LCState) -> dict:
    """Delegate 路径：为子 Agent 注入任务上下文"""
    task = state.get("task_description", "")
    if task:
        return {"messages": [HumanMessage(content=task)]}
    return {}


# ============================================================
#  统一路由函数
# ============================================================

def _agent_routing(state: LCState) -> Literal["mode_tools", "reflector", "__end__"]:
    """agent 后的路由（ReAct 循环内）

    - 有 tool_calls → mode_tools
    - 在 plan 执行中 + 无 tool_calls → reflector
    - 否则 → END（react 完成）
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

    return END


def _after_tools(state: LCState) -> Literal["agent", "supervisor"]:
    """retry_tracker 后路由：回到 agent 继续循环，或超限保护"""
    iterations = state.get("supervisor_iterations", 0)
    if iterations > MAX_SUPERVISOR_ITERATIONS:
        return "__end__"

    return "agent"


def _plan_ready(state: LCState) -> Literal["step_inject", "__end__"]:
    """plan_create 后路由：计划就绪 → step_inject，失败 → END"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return END
    try:
        plan = Plan(**plan_data)
        if plan.status == "active" and plan.current():
            return "step_inject"
    except Exception:
        pass
    return END


def _reflect_done(state: LCState) -> Literal["step_inject", "__end__"]:
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
    if current and current.status in ("pending", "in_progress"):
        return "step_inject"

    return END


# ============================================================
#  SupervisorAgent
# ============================================================

class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "主控 Agent：Agent-as-Entry 架构，一次 LLM 调用完成思考+路由"

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
        """构建 Agent-as-Entry 架构图

        agent 是唯一入口，agent 响应后由路由提取节点决定路径。
        """
        builder = StateGraph(LCState)
        mode_tool_node = ModeAwareToolNode(tools=self.tools)

        # === 核心节点 ===
        builder.add_node("agent", self._call_llm)
        builder.add_node("extract_decision", _extract_decision_node)
        builder.add_node("mode_tools", mode_tool_node)
        builder.add_node("retry_tracker", _increment_retry)

        # === Plan 路径 ===
        builder.add_node("plan_create", plan_create_from_agent)
        builder.add_node("step_inject", _step_inject)
        builder.add_node("reflector", lambda state: self._reflect_node(state))

        # === Delegate 路径（在条件分支中按需创建）===

        # === 图连接 ===

        # 入口：agent 是唯一入口
        builder.add_edge(START, "agent")

        # agent → 路由提取 → 条件路由
        builder.add_edge("agent", "extract_decision")

        # extract_decision 后：检查 plan_steps 和 delegate
        if self.sub_agents:
            # 有子 Agent → 先检查 plan，再检查 delegate，最后 END
            builder.add_conditional_edges("extract_decision", should_create_plan, {
                "plan_create": "plan_create",
                "__end__": "_check_delegate",
            })

            # delegate 检查（空路由节点）
            builder.add_node("_check_delegate", lambda state: {})
            builder.add_conditional_edges("_check_delegate", delegate_routing, {
                **{f"{n}_agent": f"{n}_agent" for n in self.sub_agents},
                "__end__": END,
            })

            # delegate 路径
            builder.add_node("delegate_inject", _delegate_inject)
            for name, agent_obj in self.sub_agents.items():
                builder.add_node(f"{name}_agent", agent_obj.get_graph())
            for name in self.sub_agents:
                builder.add_edge("delegate_inject", f"{name}_agent")
                builder.add_edge(f"{name}_agent", END)
        else:
            # 无子 Agent → plan 或 END
            builder.add_conditional_edges("extract_decision", should_create_plan, {
                "plan_create": "plan_create",
                "__end__": END,
            })

        # --- ReAct 路径（agent 有 tool_calls 时）---
        builder.add_conditional_edges("agent", _agent_routing, {
            "mode_tools": "mode_tools",
            "reflector": "reflector",  # plan 执行中的步骤完成后
            "__end__": END,
        })
        builder.add_edge("mode_tools", "retry_tracker")
        builder.add_conditional_edges("retry_tracker", _after_tools, {
            "agent": "agent",
            "__end__": END,
        })

        # --- Plan 路径 ---
        builder.add_conditional_edges("plan_create", _plan_ready, {
            "step_inject": "step_inject",
            "__end__": END,
        })
        builder.add_edge("step_inject", "agent")  # 步骤执行通过 agent
        builder.add_conditional_edges("reflector", _reflect_done, {
            "step_inject": "step_inject",
            "__end__": END,
        })

        return builder.compile(checkpointer=self.checkpoint)

    def _reflect_node(self, state: LCState) -> dict:
        """反思节点：评估步骤执行结果"""
        from LangCode.planning.reflector import reflect_node
        return reflect_node(state, self.llm)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_system_prompt(self) -> str:
        return AGENT_PROMPT
