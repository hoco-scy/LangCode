"""Reflector 节点：评估步骤执行结果，决定下一步行动"""

from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan

log = get_logger("planning.reflector")

REFLECT_PROMPT = """你是一个任务执行的反思评估者。

当前计划：
{plan_display}

请评估刚完成的步骤执行情况，决定下一步行动：

1. 如果当前步骤成功完成，返回 "continue"
2. 如果当前步骤失败但可以重试，返回 "retry" 并说明改进方案
3. 如果当前步骤失败且无法恢复，返回 "skip" 并说明原因
4. 如果需要调整计划，返回 "replan" 并说明调整建议

返回 JSON（不要包含其他文字）：
{{
  "action": "continue|retry|skip|replan",
  "reason": "原因说明",
  "adjustment": "如果是 replan，给出调整建议"
}}
"""


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
    messages = [SystemMessage(content=prompt)]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        import json
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)
        action = result.get("action", "continue")
        reason = result.get("reason", "")
        adjustment = result.get("adjustment", "")

        log.info("反思结果: action=%s reason=%s", action, reason)

        if action == "continue":
            plan.mark_current_done(reason)
        elif action == "retry":
            plan.mark_current_failed(f"重试: {reason}")
            current.status = "in_progress"  # 重新设为进行中
        elif action == "skip":
            plan.current().status = "skipped"
            plan.current_step += 1
            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
        elif action == "replan":
            plan.reflection = f"需要调整: {adjustment}"

        return {"current_plan": plan.model_dump()}
    except Exception as e:
        log.error("反思失败: %s", e)
        # 默认标记完成并继续
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
