"""Plan 工具：将计划创建暴露为 LLM 可调用的工具

核心改动：不再依赖文本解析编号列表来识别"需要创建计划"，
而是让 LLM 通过 tool calling 主动调用 plan_create 工具。
这利用了 LLM 擅长 tool calling 的特性，消除了文本信号与工具信号的冲突。
"""

import json
from langchain.tools import tool
from pydantic import BaseModel, Field


class PlanCreateInput(BaseModel):
    goal: str = Field(description="计划的最终目标")
    steps: list[str] = Field(
        description="计划步骤列表，每个元素是一个步骤描述，至少包含2个步骤",
        min_length=2,
    )


@tool("plan_create", args_schema=PlanCreateInput)
def plan_create(goal: str, steps: list[str]) -> str:
    """创建多步执行计划。当任务需要多个步骤才能完成时，调用此工具制定计划，系统会逐步执行每一步。简单任务（只需一步操作）请直接使用对应工具。"""
    return json.dumps(
        {"goal": goal, "steps": steps, "total": len(steps)},
        ensure_ascii=False,
    )


plan_tools = [plan_create]
