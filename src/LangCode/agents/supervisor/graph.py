# 主智能体 —— ReAct 循环 + Plan-and-Execute 双模式
# 简单任务: Think → Act → Observe 循环
# 复杂任务: Plan → Execute Step → Reflect → Next Step 循环

from typing import Literal

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
from LangCode.shared.logger import get_logger
from LangCode.agents.supervisor.prompts import *
from LangCode.planning.schema import Plan

log = get_logger("supervisor.graph")

MAX_TOOL_RETRIES = 3


# ============================================================
#  ReAct 核心节点
# ============================================================

def _call_llm(state: LCState, llm: ChatOpenAI) -> dict:
    """ReAct 的 Think 步骤：调用 LLM，模型自行决定是调用工具还是直接回复"""
    msg_count = len(state["messages"])
    retry_count = state.get("tool_retry_count", 0)
    log.debug("调用 LLM，消息数: %d, 重试: %d", msg_count, retry_count)

    messages = list(state["messages"])

    # 重试次数过多时提示 LLM 放弃工具调用
    if retry_count >= MAX_TOOL_RETRIES:
        log.warning("工具重试已达上限 (%d)", MAX_TOOL_RETRIES)
        messages.append(ToolMessage(
            content="[系统提示] 工具调用已连续失败多次，请直接基于已有信息回复用户。",
            tool_call_id="system_retry_limit"
        ))

    # 注入记忆上下文
    memory_context = state.get("memory_context", "")
    if memory_context:
        insert_idx = 0
        for i, m in enumerate(messages):
            if hasattr(m, 'type') and m.type == 'system':
                insert_idx = i + 1
        messages.insert(insert_idx, SystemMessage(
            id="memory_context",
            content=f"[已知的相关记忆]\n{memory_context}"
        ))

    # 注入当前计划摘要（如果有）
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active":
                plan_summary = plan.to_display()
                messages.insert(insert_idx, SystemMessage(
                    id="current_plan",
                    content=f"[当前执行计划]\n{plan_summary}"
                ))
        except Exception:
            pass

    response = llm.invoke(messages)
    if response.tool_calls:
        log.info("LLM 请求工具: %s", [tc["name"] for tc in response.tool_calls])
    else:
        log.debug("LLM 直接回复: %s...", (response.content or "")[:120])
    return {"messages": [response], "tool_retry_count": 0, "memory_context": ""}


def _increment_retry(state: LCState) -> dict:
    """工具执行后递增重试计数"""
    return {"tool_retry_count": state.get("tool_retry_count", 0) + 1}


# ============================================================
#  Plan-and-Execute 节点
# ============================================================

def _planner_node(state: LCState, llm: ChatOpenAI) -> dict:
    """规划节点：分析任务，决定是否需要制定计划"""
    from LangCode.planning.planner import create_plan_node
    return create_plan_node(state, llm)


def _step_executor_node(state: LCState, llm: ChatOpenAI) -> dict:
    """步骤执行节点：执行计划中的当前步骤"""
    from LangCode.planning.executor import execute_step_node
    return execute_step_node(state, llm)


def _reflector_node(state: LCState, llm: ChatOpenAI) -> dict:
    """反思节点：评估步骤执行结果"""
    from LangCode.planning.reflector import reflect_node
    return reflect_node(state, llm)


def _should_plan(state: LCState) -> Literal["planner", "step_executor", "react"]:
    """路由：检查是否需要进入规划模式"""
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            if plan.status == "active":
                # 如果计划已有步骤，直接执行；否则需要规划
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
    if plan.status == "completed" or plan.status == "abandoned":
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
        return "agent"  # 需要工具执行，回到 ReAct 循环
    return "reflector"  # 纯文本回复，进入反思


# ============================================================
#  SupervisorAgent 类
# ============================================================

class SupervisorAgent:
    def __init__(self, llm: ChatOpenAI, sys_checkpoint: Checkpointer, sys_tools: list[BaseTool]) -> None:
        self.tools = sys_tools
        self.llm = llm.bind_tools(self.tools)
        self.checkpoint = sys_checkpoint
        self.graph = self.make_graph()

    def make_graph(self) -> CompiledStateGraph:
        builder = StateGraph(LCState)  # type: ignore[arg-type]
        tool_node = ToolNode(tools=self.tools)

        # ---- ReAct 节点 ----
        builder.add_node("agent", lambda state: _call_llm(state, self.llm))
        builder.add_node("tools", tool_node)
        builder.add_node("retry_tracker", _increment_retry)

        # ---- Plan-and-Execute 节点 ----
        builder.add_node("planner", lambda state: _planner_node(state, self.llm))
        builder.add_node("step_executor", lambda state: _step_executor_node(state, self.llm))
        builder.add_node("reflector", lambda state: _reflector_node(state, self.llm))

        # ---- 图连接 ----
        # 入口：先经过 agent 节点
        builder.add_edge(START, "agent")

        # agent 节点：有工具调用 → tools，否则 → END
        builder.add_conditional_edges("agent", should_use_tools)

        # tools → retry_tracker → 检查是否有活跃计划
        builder.add_edge("tools", "retry_tracker")
        builder.add_conditional_edges("retry_tracker", _should_plan, {
            "planner": "planner",
            "step_executor": "step_executor",
            "react": "agent",
        })

        # planner → 检查是否还有步骤
        builder.add_conditional_edges("planner", _plan_or_end)

        # step_executor → 检查是否需要工具调用
        builder.add_conditional_edges("step_executor", _after_step)

        # reflector → 检查是否继续
        builder.add_edge("reflector", "step_executor")

        return builder.compile(checkpointer=self.checkpoint)

    @staticmethod
    def get_agent_prompt():
        return AGENT_PROMPT

    def get_graph(self) -> CompiledStateGraph:
        return self.graph