"""StepExecutor 节点：执行计划中的当前步骤"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan

log = get_logger("planning.executor")

EXECUTOR_PROMPT = """你正在执行一个多步骤任务计划中的某一步。

当前计划：
{plan_display}

你当前需要执行第 {step_id} 步：{step_desc}

请使用可用工具完成这一步。完成后，用简洁的文字总结执行结果。
如果这一步不需要工具调用（如分析、总结），直接回复即可。
"""


def execute_step_node(state: LCState, llm: ChatOpenAI) -> dict:
    """执行当前计划步骤"""
    plan_data = state.get("current_plan")
    if not plan_data:
        log.warning("execute_step: 无计划，跳过")
        return {}

    plan = Plan(**plan_data)
    current = plan.current()
    if not current:
        log.info("execute_step: 所有步骤已完成")
        return {"current_plan": plan.model_dump()}

    log.info("执行步骤 %d: %s", current.step_id, current.description)
    current.status = "in_progress"

    # 构建执行提示
    prompt = EXECUTOR_PROMPT.format(
        plan_display=plan.to_display(),
        step_id=current.step_id,
        step_desc=current.description,
    )

    # 注入到消息中，让 LLM 执行
    messages = list(state["messages"]) + [SystemMessage(content=prompt)]
    response = llm.invoke(messages)

    # 如果 LLM 返回了工具调用，不在此处处理（由 ReAct 循环处理）
    # 如果是纯文本回复，记录为步骤结果
    if not response.tool_calls:
        result = response.content or ""
        log.info("步骤 %d 完成: %s", current.step_id, result[:100])
        plan.mark_current_done(result[:500])
    else:
        log.info("步骤 %d 需要工具调用", current.step_id)

    return {
        "messages": [response],
        "current_plan": plan.model_dump(),
    }
