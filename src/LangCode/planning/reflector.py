"""Reflector 节点：评估步骤执行结果，决定下一步行动

核心改动：
1. 注入最近对话消息作为执行上下文，让反思决策有据可依
2. 使用 structured output 替代 JSON 文本解析，提高可靠性
3. 反思结果中增加步骤摘要，便于后续步骤理解前序进展
"""

from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, BaseMessage
from langchain_core.tools import tool as lc_tool
from pydantic import BaseModel, Field

from LangCode.shared.types import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan

log = get_logger("planning.reflector")

REFLECT_PROMPT = """你是一个任务执行的反思评估者。

当前计划：
{plan_display}

请评估刚完成的步骤执行情况，决定下一步行动。

评估要点：
- 步骤是否完成了预期目标？
- 执行结果是否正确？
- 是否需要调整后续步骤？

你必须调用 reflect_decision 工具来报告评估结果。
- action="continue"：步骤成功完成，继续下一步
- action="retry"：步骤失败，需要重试
- action="skip"：步骤无法完成，跳过
- action="replan"：需要调整后续计划

不要输出文本，直接调用工具。"""


class ReflectDecision(BaseModel):
    """反思决策的结构化输出"""
    action: Literal["continue", "retry", "skip", "replan"] = Field(
        description="下一步行动：continue（继续）、retry（重试）、skip（跳过）、replan（调整计划）"
    )
    reason: str = Field(description="决策理由")
    step_summary: str = Field(
        default="",
        description="当前步骤的执行结果摘要，用于后续步骤理解前序进展"
    )
    adjustment: str = Field(
        default="",
        description="仅当 action=replan 时，给出调整建议"
    )


@lc_tool
def reflect_decision(action: str, reason: str, step_summary: str = "", adjustment: str = "") -> dict:
    """评估步骤执行结果并决定下一步行动。

    Args:
        action: 下一步行动，必须是 continue/retry/skip/replan 之一
        reason: 决策理由
        step_summary: 当前步骤的执行结果摘要
        adjustment: 仅当 action=replan 时，给出调整建议
    """
    return {"action": action, "reason": reason, "step_summary": step_summary, "adjustment": adjustment}


def reflect_node(state: LCState, llm: ChatOpenAI) -> dict:
    """反思节点：评估执行结果，更新计划状态"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return {}

    plan = Plan(**plan_data)
    current = plan.current()
    if not current:
        return {"current_plan": plan.model_dump()}

    log.info("反思步骤 %d: %s", current.step_id, current.description)

    prompt = REFLECT_PROMPT.format(plan_display=plan.to_display())
    messages: list[BaseMessage] = [SystemMessage(content=prompt)]

    # 注入最近 5 条消息作为执行上下文
    recent = state.get("messages", [])[-5:]
    messages.extend(recent)

    try:
        bound_llm = llm.bind_tools([reflect_decision])
        response = bound_llm.invoke(messages)

        tc = None
        for t in (response.tool_calls or []):
            if t["name"] == "reflect_decision":
                tc = t
                break

        if not tc:
            log.warning("反思: 模型未调用 reflect_decision，默认标记完成")
            plan.mark_current_done("反思未返回决策，默认继续")
            # 标记下一个步骤为 in_progress
            next_step = plan.current()
            if next_step and next_step.status == "pending":
                next_step.status = "in_progress"
            return {"current_plan": plan.model_dump()}

        args = tc["args"]
        action = args.get("action", "continue")
        reason = args.get("reason", "")
        step_summary = args.get("step_summary", "") or reason
        adjustment = args.get("adjustment", "")

        log.info("反思结果: action=%s reason=%s", action, reason)

        if action == "continue":
            plan.mark_current_done(step_summary)
            # 标记下一个步骤为 in_progress，确保 after_tools_routing 正确路由到 reflect
            next_step = plan.current()
            if next_step and next_step.status == "pending":
                next_step.status = "in_progress"
        elif action == "retry":
            plan.mark_current_failed(f"重试: {reason}")
            current.status = "in_progress"
        elif action == "skip":
            current.status = "skipped"
            plan.current_step += 1
            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
            else:
                next_step = plan.current()
                if next_step and next_step.status == "pending":
                    next_step.status = "in_progress"
        elif action == "replan":
            plan.reflection = f"需要调整: {adjustment}"

        return {"current_plan": plan.model_dump()}
    except Exception as e:
        log.error("反思失败: %s", e)
        plan.mark_current_done("反思失败，默认继续")
        next_step = plan.current()
        if next_step and next_step.status == "pending":
            next_step.status = "in_progress"
        return {"current_plan": plan.model_dump()}


def should_continue_plan(state: LCState) -> Literal["execute", "replan", "end"]:
    """路由：判断是否需要继续执行计划"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return "end"

    plan = Plan(**plan_data)

    if plan.status == "completed":
        log.info("计划已完成")
        return "end"

    if plan.status == "abandoned":
        log.info("计划已放弃")
        return "end"

    if plan.reflection and "需要调整" in (plan.reflection or ""):
        log.info("计划需要调整")
        return "replan"

    current = plan.current()
    if current and current.status in ("pending", "in_progress"):
        return "execute"

    return "end"
