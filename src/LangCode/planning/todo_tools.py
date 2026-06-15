"""Todo 工具 — 将计划作为普通工具管理。

替代原 plan_create + reflector + mark_step 的复杂图节点方案。
LLM 在 ReAct 循环中自行调用这些工具管理计划，系统通过注入上下文引导行为。

工具本身只返回成功 JSON，真正的状态更新在 router.process_tool_results() 中完成。
原因：LangChain tool 无法直接修改 LangGraph 状态。
"""

import json
from pydantic import BaseModel, Field


# ── 输入 Schema ──

class WriteTodoInput(BaseModel):
    """write_todo 工具输入"""
    goal: str = Field(description="计划的最终目标")
    steps: list[str] = Field(
        description="计划步骤列表，每个元素是一个步骤描述，至少包含 2 个步骤",
        min_length=2,
    )


class UpdateTodoInput(BaseModel):
    """update_todo 工具输入"""
    step_index: int = Field(
        description="步骤编号（1-based），传 0 表示更新整个计划的状态",
    )
    status: str = Field(
        description="目标状态：done（完成）、failed（失败）、skipped（跳过）、in_progress（进行中）、completed（整个计划完成）、abandoned（放弃计划）",
    )
    result: str = Field(
        default="",
        description="执行结果摘要或失败原因",
    )


class ModifyTodoInput(BaseModel):
    """modify_todo 工具输入"""
    steps: list[str] | None = Field(
        default=None,
        description="替换整个步骤列表（完全重写）",
    )
    add_steps: list[str] | None = Field(
        default=None,
        description="追加新步骤到列表末尾",
    )
    remove_indices: list[int] | None = Field(
        default=None,
        description="删除指定步骤（1-based 编号列表）",
    )


# ── 工具创建 ──

def create_todo_tools():
    """创建 write_todo / update_todo / modify_todo 三个 LangChain 工具。"""
    from langchain.tools import tool as langchain_tool

    @langchain_tool("write_todo", args_schema=WriteTodoInput)
    def write_todo(goal: str, steps: list[str]) -> str:
        """创建多步执行计划。

        当任务需要 3 步及以上操作时，调用此工具制定计划。
        系统会在每轮对话中注入计划上下文，提醒你按计划执行。

        简单任务（1-2 步）请直接使用对应工具，无需创建计划。
        """
        return json.dumps(
            {"goal": goal, "steps": steps, "total": len(steps)},
            ensure_ascii=False,
        )

    @langchain_tool("update_todo", args_schema=UpdateTodoInput)
    def update_todo(step_index: int, status: str, result: str = "") -> str:
        """更新计划步骤的状态。

        每完成一个步骤后，及时调用此工具标记为 done 并附上结果。
        如果步骤失败，标记为 failed 并说明原因。
        所有步骤完成后，调用此工具（step_index=0, status=completed）标记计划完成。
        """
        return json.dumps(
            {"step_index": step_index, "status": status, "result": result},
            ensure_ascii=False,
        )

    @langchain_tool("modify_todo", args_schema=ModifyTodoInput)
    def modify_todo(steps: list[str] | None = None, add_steps: list[str] | None = None, remove_indices: list[int] | None = None) -> str:
        """修改当前计划的步骤。

        支持三种操作（可组合使用）：
        - steps: 替换整个步骤列表（完全重写计划）
        - add_steps: 追加新步骤到列表末尾
        - remove_indices: 删除指定步骤（1-based 编号）
        """
        return json.dumps(
            {"steps": steps, "add_steps": add_steps, "remove_indices": remove_indices},
            ensure_ascii=False,
        )

    return [write_todo, update_todo, modify_todo]
