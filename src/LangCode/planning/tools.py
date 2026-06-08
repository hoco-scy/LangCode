"""规划相关工具：供 Agent 调用的计划操作"""

from typing import Optional
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("planning.tools")

# 全局引用
_store = None


def init_planning_tools():
    """初始化规划工具（当前无需额外依赖）"""
    pass


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


@tool("plan_show")
def plan_show() -> dict:
    """显示当前正在执行的计划及其进度。"""
    # 这个工具主要由 graph 节点在 state 中读取，这里返回提示
    return {"success": True, "message": "请通过 graph state 查看当前计划"}
