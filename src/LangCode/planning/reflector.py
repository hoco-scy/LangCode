"""Reflector 节点：评估步骤执行结果，决定下一步行动

核心改动：
1. 注入最近对话消息作为执行上下文，让反思决策有据可依
2. 使用 structured output 替代 JSON 文本解析，提高可靠性
3. 反思结果中增加步骤摘要，便于后续步骤理解前序进展
"""

from typing import Literal, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, BaseMessage
from pydantic import BaseModel, Field

from LangCode.shared.state import LCState
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

根据评估结果选择行动：
1. continue — 当前步骤成功，继续下一步
2. retry — 当前步骤失败但可以重试（说明改进方案）
3. skip — 当前步骤无法完成但可以跳过（说明原因）
4. replan — 需要调整整体计划（给出调整建议）
"""


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

    # 构建反思上下文：计划 + 最近对话消息
    prompt = REFLECT_PROMPT.format(plan_display=plan.to_display())
    messages: list[BaseMessage] = [SystemMessage(content=prompt)]

    # 注入最近 5 条消息作为执行上下文（包含工具调用结果）
    recent = state.get("messages", [])[-5:]
    messages.extend(recent)

    try:
        structured_llm = llm.with_structured_output(ReflectDecision)
        result = structured_llm.invoke(messages)

        if not isinstance(result, ReflectDecision):
            log.warning("反思: 非预期返回类型，默认标记完成")
            plan.mark_current_done("反思返回类型异常，默认继续")
            return {"current_plan": plan.model_dump()}

        action = result.action
        reason = result.reason
        step_summary = result.step_summary or reason
        adjustment = result.adjustment

        log.info("反思结果: action=%s reason=%s", action, reason)

        if action == "continue":
            plan.mark_current_done(step_summary)
        elif action == "retry":
            plan.mark_current_failed(f"重试: {reason}")
            current.status = "in_progress"
        elif action == "skip":
            current.status = "skipped"
            plan.current_step += 1
            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
        elif action == "replan":
            plan.reflection = f"需要调整: {adjustment}"

        return {"current_plan": plan.model_dump()}
    except Exception as e:
        log.error("反思失败: %s", e)
        plan.mark_current_done("反思失败，默认继续")
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
