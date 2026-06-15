"""Reflector 节点：评估步骤执行结果，决定下一步行动

核心改动：
1. 注入最近对话消息作为执行上下文，让反思决策有据可依
2. 使用 structured output 替代 JSON 文本解析，提高可靠性
3. 反思结果中增加步骤摘要，便于后续步骤理解前序进展

修复：
- 上下文从 5 条扩大到 15 条，确保覆盖工具执行结果
- 提取工具执行摘要注入反思 prompt
- 改进 fallback：从工具结果中提取实际执行内容
"""

from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, BaseMessage, AIMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from pydantic import BaseModel, Field

from LangCode.shared.types import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan

log = get_logger("planning.reflector")

REFLECT_PROMPT = """你是一个任务执行的反思评估者。

当前计划：
{plan_display}

{tool_summary}

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

不要输出文本，直接调用 reflect_decision 工具。"""


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


def _extract_tool_summary(messages: list, lookback: int = 10) -> str:
    """从最近的消息中提取工具执行摘要。

    找到最近一轮 AI 的 tool_calls 及其对应的 ToolMessage 结果，
    格式化为可读的摘要供反思器参考。
    """
    recent = messages[-lookback:]
    tool_results = []

    # 找最近的 AIMessage with tool_calls
    for i, msg in enumerate(recent):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.get("name", "unknown")
                tool_args = tc.get("args", {})
                # 找对应的 ToolMessage
                tc_id = tc.get("id", "")
                result_content = ""
                for subsequent in recent[i+1:]:
                    if isinstance(subsequent, ToolMessage) and subsequent.tool_call_id == tc_id:
                        content = subsequent.content if isinstance(subsequent.content, str) else str(subsequent.content)
                        result_content = content[:300]
                        break

                if tool_name == "plan_create":
                    continue  # 跳过 plan_create 本身

                arg_summary = ", ".join(f"{k}={str(v)[:50]}" for k, v in list(tool_args.items())[:3])
                tool_results.append(
                    f"- {tool_name}({arg_summary}): {result_content[:200]}"
                )

    if not tool_results:
        return ""

    return "最近的工具执行结果：\n" + "\n".join(tool_results[-8:])


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

    # 提取工具执行摘要
    tool_summary = _extract_tool_summary(state.get("messages", []))

    prompt = REFLECT_PROMPT.format(
        plan_display=plan.to_display(),
        tool_summary=tool_summary,
    )
    messages: list[BaseMessage] = [SystemMessage(content=prompt)]

    # 注入最近 15 条消息作为执行上下文（扩大窗口以覆盖工具结果）
    recent = state.get("messages", [])[-15:]
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
            # LLM 未调用工具 → 尝试从工具结果中提取摘要作为 fallback
            fallback_summary = _extract_fallback_summary(state.get("messages", []))
            log.warning("反思: 模型未调用 reflect_decision，使用 fallback")
            plan.mark_current_done(fallback_summary)
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
        fallback_summary = _extract_fallback_summary(state.get("messages", []))
        plan.mark_current_done(f"反思失败: {fallback_summary}")
        next_step = plan.current()
        if next_step and next_step.status == "pending":
            next_step.status = "in_progress"
        return {"current_plan": plan.model_dump()}


def _extract_fallback_summary(messages: list) -> str:
    """从最近的工具结果中提取执行摘要（反思器 fallback）。

    当 LLM 不调用 reflect_decision 时，从工具执行结果中提取关键信息。
    """
    recent = messages[-10:]
    summaries = []
    for msg in recent:
        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            name = getattr(msg, "name", "tool")
            # 提取关键信息（成功/失败/文件路径等）
            preview = content[:150].replace("\n", " ")
            summaries.append(f"{name}: {preview}")
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                if name not in ("plan_create", "reflect_decision"):
                    summaries.append(f"调用 {name}")

    if summaries:
        return "; ".join(summaries[-3:])
    return "步骤执行完成"


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
