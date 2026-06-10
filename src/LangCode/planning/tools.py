"""规划相关工具：供 Agent 调用的计划操作"""

from typing import Optional, Any
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("planning.tools")


class PlanCreateInput(BaseModel):
    goal: str = Field(description="任务目标描述")
    steps: list[str] = Field(description="步骤列表，每个元素是一个步骤的描述")


@tool("plan_create", args_schema=PlanCreateInput)
def plan_create(goal: str, steps: list[str]) -> dict:
    """创建一个任务执行计划。用于将复杂任务分解为可执行的步骤。"""
    from LangCode.planning.schema import Plan, PlanStep
    try:
        plan = Plan(
            goal=goal,
            steps=[PlanStep(step_id=i + 1, description=s) for i, s in enumerate(steps)]
        )
        log.info("plan_create: goal=%s steps=%d", goal, len(steps))
        return {"success": True, "plan": plan.model_dump(), "display": plan.to_display()}
    except Exception as e:
        log.error("plan_create 失败: %s", e)
        return {"success": False, "error": str(e)}


class PlanShowInput(BaseModel):
    current_plan: Optional[dict] = Field(
        default=None,
        description="当前计划的完整 dict（从 system message 中的 [当前执行计划] 摘要还原，或传 None 表示无计划）"
    )


@tool("plan_show", args_schema=PlanShowInput)
def plan_show(current_plan: Optional[dict] = None) -> dict:
    """显示当前正在执行的计划及其进度。在有活跃计划时调用，以获得结构化的进度视图。"""
    from LangCode.planning.schema import Plan
    if current_plan is None:
        return {"success": True, "message": "当前没有活跃的执行计划。如需为任务创建计划，请使用 plan_create。"}
    try:
        plan = Plan(**current_plan)
        display = plan.to_display()
        log.info("plan_show: goal=%s status=%s steps=%d",
                 plan.goal, plan.status, len(plan.steps))
        return {"success": True, "display": display, "status": plan.status}
    except Exception as e:
        log.warning("plan_show: 无法解析计划数据: %s", e)
        return {"success": False, "error": f"计划数据格式错误: {e}"}
