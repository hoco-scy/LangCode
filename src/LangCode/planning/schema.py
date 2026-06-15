"""任务规划的数据模型"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """单个计划步骤"""
    step_id: int = Field(description="步骤编号，从 1 开始")
    description: str = Field(description="步骤描述，明确要做什么")
    status: Literal["pending", "in_progress", "done", "failed", "skipped"] = Field(
        default="pending", description="步骤状态"
    )
    result: Optional[str] = Field(default=None, description="执行结果摘要")
    error: Optional[str] = Field(default=None, description="失败原因")


class Plan(BaseModel):
    """任务执行计划"""
    goal: str = Field(description="最终目标的简要描述")
    steps: list[PlanStep] = Field(description="分解后的步骤列表")
    current_step: int = Field(default=0, description="当前执行到的步骤索引（0-based）")
    status: Literal["active", "completed", "abandoned"] = Field(
        default="active", description="计划状态"
    )
    reflection: Optional[str] = Field(default=None, description="最近一次反思的结论")

    def current(self) -> Optional[PlanStep]:
        """获取当前步骤"""
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def mark_current_done(self, result: str):
        """标记当前步骤完成"""
        step = self.current()
        if step:
            step.status = "done"
            step.result = result
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.status = "completed"

    def mark_current_failed(self, error: str):
        """标记当前步骤失败"""
        step = self.current()
        if step:
            step.status = "failed"
            step.error = error

    def mark_completed(self):
        """标记整个计划完成"""
        self.status = "completed"
        for s in self.steps:
            if s.status == "pending":
                s.status = "skipped"

    def mark_abandoned(self):
        """标记计划放弃"""
        self.status = "abandoned"

    def to_display(self) -> str:
        """生成可读的计划展示"""
        lines = [f"[目标] {self.goal}", f"状态: {self.status}", ""]
        for step in self.steps:
            status_icon = {
                "pending": "[ ]", "in_progress": "[>]", "done": "[x]",
                "failed": "[!]", "skipped": "[-]"
            }.get(step.status, "[?]")
            marker = " <-- 当前" if step.step_id - 1 == self.current_step and self.status == "active" else ""
            lines.append(f"  {status_icon} {step.step_id}. {step.description}{marker}")
            if step.result:
                lines.append(f"     结果: {step.result[:100]}")
            if step.error:
                lines.append(f"     错误: {step.error[:100]}")
        if self.reflection:
            lines.append(f"\n[反思] {self.reflection}")
        return "\n".join(lines)
