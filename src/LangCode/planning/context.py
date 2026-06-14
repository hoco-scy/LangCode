"""PlanContextInjector — 将计划上下文注入 LLM 消息。

在 Supervisor._call_llm() 的消息组装阶段调用。
注入策略根据 current_step 状态切换。
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import SystemMessage

from LangCode.planning.schema import Plan
from LangCode.shared.logger import get_logger

log = get_logger("planning.context")


def inject_plan_context(plan_data: Optional[dict]) -> list[SystemMessage]:
    """构建计划上下文注入消息。

    Args:
        plan_data: LCState.current_plan (dict 形式的 Plan)

    Returns:
        要注入的 SystemMessage 列表，供 _call_llm 插入到消息中
    """
    if not plan_data:
        return []

    try:
        plan = Plan(**plan_data)
    except Exception:
        return []

    if plan.status == "completed":
        return [SystemMessage(
            id="plan_complete",
            content=f"计划已完成: {plan.goal}\n\n你现在可以自由响应用户的后续请求。"
        )]
    if plan.status == "abandoned":
        return []

    current = plan.current()
    if not current:
        return []

    messages: list[SystemMessage] = []

    # 已完成步骤摘要
    completed = [s for s in plan.steps if s.status == "done"]
    if completed:
        summary = "\n".join(
            f"  步骤 {s.step_id}: {(s.result or '')[:150]}"
            for s in completed if s.result
        )
        messages.append(SystemMessage(
            id="plan_completed_summary",
            content=f"已完成步骤:\n{summary}"
        ))

    # 当前步骤指令
    if current.status == "in_progress":
        messages.append(SystemMessage(
            id="plan_execution",
            content=(
                f"正在执行计划: {plan.goal}\n\n"
                f"当前步骤 ({current.step_id}/{len(plan.steps)}): {current.description}\n\n"
                f"严格完成当前步骤，不要偏离。完成后简要总结结果。\n"
                f"不要重复已完成的步骤。"
            )
        ))
    elif current.status == "pending":
        messages.append(SystemMessage(
            id="plan_next_step",
            content=(
                f"计划下一步: {plan.goal}\n\n"
                f"即将执行步骤 {current.step_id}: {current.description}\n\n"
                f"{plan.to_display()}"
            )
        ))
    elif current.status == "failed":
        messages.append(SystemMessage(
            id="plan_failed_step",
            content=(
                f"步骤 {current.step_id} 执行失败: {current.error}\n\n"
                f"请分析失败原因并决定: 重试/跳过/调整计划。"
            )
        ))

    return messages
