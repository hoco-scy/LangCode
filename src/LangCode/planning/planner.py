"""Planner 节点：将复杂任务分解为可执行的步骤"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan, PlanStep

log = get_logger("planning.planner")

PLANNER_PROMPT = """你是一个任务规划专家。给定用户的任务目标，将其分解为清晰、可执行的步骤。

要求：
- 每个步骤应该是单一、明确的动作
- 步骤之间有逻辑顺序
- 通常 3-8 个步骤为宜
- 最后一步应该是验证或总结

返回 JSON 格式（不要包含其他文字）：
{{
  "goal": "目标简述",
  "steps": [
    {{"step_id": 1, "description": "步骤描述"}},
    {{"step_id": 2, "description": "步骤描述"}}
  ]
}}
"""


def create_plan_node(state: LCState, llm: ChatOpenAI) -> dict:
    """规划节点：调用 LLM 生成任务计划"""
    task = state.get("task_description", "")
    if not task:
        # 从最后一条用户消息中提取任务
        for msg in reversed(state["messages"]):
            if hasattr(msg, 'type') and msg.type == 'human':
                task = msg.content
                break

    log.info("创建计划: task=%s", task[:100])

    # 构建规划请求
    memory_context = state.get("memory_context", "")
    context_part = f"\n\n相关记忆：\n{memory_context}" if memory_context else ""

    prompt = PLANNER_PROMPT + context_part
    messages = [
        SystemMessage(content=prompt),
        SystemMessage(content=f"请为以下任务制定执行计划：\n{task}")
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # 解析 JSON
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        plan_data = json.loads(content)
        plan = Plan(
            goal=plan_data["goal"],
            steps=[PlanStep(step_id=s["step_id"], description=s["description"]) for s in plan_data["steps"]]
        )

        log.info("计划创建成功: %d 步", len(plan.steps))
        print(f"\n{plan.to_display()}\n")

        return {
            "current_plan": plan.model_dump(),
            "plan_step_index": 0,
            "task_description": task,
        }
    except Exception as e:
        log.error("计划创建失败: %s", e)
        # 失败时返回一个简单的单步计划
        fallback = Plan(
            goal=task,
            steps=[PlanStep(step_id=1, description=task, status="in_progress")]
        )
        return {
            "current_plan": fallback.model_dump(),
            "plan_step_index": 0,
            "task_description": task,
        }
