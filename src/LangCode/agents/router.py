"""agents/router — 路由决策：工具调用信号提取 + 四路分发。

参考 Claude Code 的 tool calling 驱动路由设计：
  v1: 正则解析 [route: xxx] 标签 → 不可靠
  v2: plan_create/delegate_* 工具调用 → 结构化信号 → 路由决策

plan_create 工具被调用 → 构建 Plan → current_plan
delegate_explore/review 工具被调用 → route + task_description
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage

from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan, PlanStep

log = get_logger("agents.router")


def should_use_tools(state: dict) -> str:
    """agent 节点后：有 tool_calls → "tools"，无 → "__end__"

    LangGraph 条件边判断函数。
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "__end__"


def process_tool_results(state: dict) -> dict:
    """从上一轮 LLM 的 tool_calls 中提取 plan/delegate 信号。

    这是 plan_create 和 delegate_* 工具的"真正执行者"。
    工具函数本身只返回成功 JSON，真正的 Plan 构建在此处完成。
    原因：LangChain tool 无法直接修改 LangGraph 状态。

    Returns:
        状态更新 dict（current_plan / route / task_description）
    """
    updates: dict = {}
    messages = state.get("messages", [])

    last_ai = _find_last_ai_with_tool_calls(messages)
    if not last_ai:
        return updates

    for tc in last_ai.tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})

        if name == "plan_create":
            goal = args.get("goal", "")
            steps_raw = args.get("steps", [])
            steps = [
                PlanStep(step_id=i + 1, description=str(s))
                for i, s in enumerate(steps_raw)
            ]
            plan = Plan(goal=goal or "执行计划", steps=steps)
            updates["current_plan"] = plan.model_dump()
            log.info("plan_create 工具调用: goal=%s, %d 步", goal[:50], len(steps))

        elif name.startswith("delegate_"):
            agent_name = name.replace("delegate_", "")
            task = args.get("task", "")
            updates["route"] = agent_name
            updates["task_description"] = task
            log.info("delegate 工具调用: agent=%s, task=%s", agent_name, task[:50])

    return updates


def after_tools_routing(state: dict) -> str:
    """tools + router 后：四路分发。

    优先级（从高到低）：
    1. 刚创建了计划（所有步骤 pending） → "plan_created"
    2. delegate_* 被调用 → "delegated"
    3. 有活跃计划且有 in_progress 步骤 → "reflect"
    4. 其他 → "react"（ReAct 循环继续）
    """
    plan_data = state.get("current_plan")

    # 1. 刚创建计划 → mark_step
    if plan_data and _is_newly_created(plan_data):
        return "plan_created"

    # 2. 委派 → delegate_router
    route = state.get("route", "")
    if route in ("explore", "review"):
        return "delegated"

    # 3. 计划执行中 → reflector
    if plan_data and _is_step_in_progress(plan_data):
        return "reflect"

    # 4. ReAct 循环
    return "react"


# ── 辅助函数 ──

def _find_last_ai_with_tool_calls(messages: list[BaseMessage]) -> Optional[AIMessage]:
    """从消息列表中找到最近一个含 tool_calls 的 AIMessage。"""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.tool_calls:
            return m
    return None


def _is_newly_created(plan_data: dict) -> bool:
    """判断计划是否刚创建（所有步骤都是 pending）。"""
    try:
        plan = Plan(**plan_data)
        return (
            plan.status == "active"
            and len(plan.steps) >= 2
            and all(s.status == "pending" for s in plan.steps)
        )
    except Exception:
        return False


def _is_step_in_progress(plan_data: dict) -> bool:
    """判断计划是否有步骤正在执行。"""
    try:
        plan = Plan(**plan_data)
        current = plan.current()
        return (
            plan.status == "active"
            and current is not None
            and current.status == "in_progress"
        )
    except Exception:
        return False
