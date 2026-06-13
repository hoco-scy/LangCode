"""规划相关工具：供 Agent 调用的计划操作"""

import json
from typing import Annotated

from langchain.tools import tool
from langchain_core.tools import InjectedToolArg
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field
from langgraph.types import Command

from LangCode.shared.logger import get_logger

log = get_logger("planning.tools")


class PlanCreateInput(BaseModel):
    goal: str = Field(description="任务目标描述")
    steps: list[str] = Field(description="步骤列表，每个元素是一个步骤的描述")


@tool("plan_create", args_schema=PlanCreateInput)
def plan_create(goal: str, steps: list[str],
                tool_call_id: Annotated[str, InjectedToolArg] = "") -> Command:
    """创建一个任务执行计划。用于将复杂任务分解为可执行的步骤。"""
    from LangCode.planning.schema import Plan, PlanStep
    try:
        plan = Plan(
            goal=goal,
            steps=[PlanStep(step_id=i + 1, description=s) for i, s in enumerate(steps)]
        )
        log.info("plan_create: goal=%s steps=%d", goal, len(steps))
        result = {"success": True, "plan": plan.model_dump(), "display": plan.to_display()}
        return Command(
            update={
                "messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)],
                "current_plan": plan.model_dump(),
                "plan_step_index": 0,
                "task_description": goal,
            },
        )
    except Exception as e:
        log.error("plan_create 失败: %s", e)
        result = {"success": False, "error": str(e)}
        return Command(
            update={"messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)]},
        )
