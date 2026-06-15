"""planning.schema — Plan/PlanStep 数据模型测试"""

import pytest
from LangCode.planning.schema import Plan, PlanStep


class TestPlanStep:
    def test_defaults(self):
        step = PlanStep(step_id=1, description="do something")
        assert step.status == "pending"
        assert step.result is None
        assert step.error is None

    def test_all_fields(self):
        step = PlanStep(
            step_id=2, description="test", status="done",
            result="ok", error=None,
        )
        assert step.step_id == 2
        assert step.status == "done"
        assert step.result == "ok"

    def test_valid_statuses(self):
        for s in ("pending", "in_progress", "done", "failed", "skipped"):
            step = PlanStep(step_id=1, description="x", status=s)
            assert step.status == s


class TestPlan:
    def _make_plan(self, n_steps=3):
        steps = [PlanStep(step_id=i+1, description=f"step {i+1}") for i in range(n_steps)]
        return Plan(goal="test goal", steps=steps)

    def test_create(self):
        plan = self._make_plan()
        assert plan.goal == "test goal"
        assert len(plan.steps) == 3
        assert plan.status == "active"
        assert plan.current_step == 0

    def test_current(self):
        plan = self._make_plan()
        assert plan.current().step_id == 1

    def test_current_out_of_range(self):
        plan = self._make_plan()
        plan.current_step = 99
        assert plan.current() is None

    def test_mark_current_done(self):
        plan = self._make_plan()
        plan.mark_current_done("result text")
        assert plan.steps[0].status == "done"
        assert plan.steps[0].result == "result text"
        assert plan.current_step == 1

    def test_mark_current_done_completes_plan(self):
        plan = self._make_plan(n_steps=1)
        plan.mark_current_done("done")
        assert plan.status == "completed"
        assert plan.current_step == 1

    def test_mark_current_failed(self):
        plan = self._make_plan()
        plan.mark_current_failed("error msg")
        assert plan.steps[0].status == "failed"
        assert plan.steps[0].error == "error msg"

    def test_to_display(self):
        plan = self._make_plan()
        display = plan.to_display()
        assert "test goal" in display
        assert "[ ]" in display  # pending icon
        assert "step 1" in display

    def test_to_display_with_done(self):
        plan = self._make_plan()
        plan.mark_current_done("ok")
        display = plan.to_display()
        assert "[x]" in display  # done icon for step 1
        assert "结果: ok" in display or "ok" in display
        # 当前步骤是 step 2（pending），标记为 "<-- 当前"
        assert "当前" in display or "<--" in display

    def test_model_dump_roundtrip(self):
        plan = self._make_plan()
        d = plan.model_dump()
        restored = Plan(**d)
        assert restored.goal == plan.goal
        assert len(restored.steps) == len(plan.steps)

    def test_empty_steps(self):
        plan = Plan(goal="empty", steps=[])
        assert plan.current() is None
        assert plan.status == "active"
