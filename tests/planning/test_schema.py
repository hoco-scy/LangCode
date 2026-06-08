"""planning/schema.py — Plan + PlanStep 纯函数测试"""

from LangCode.planning.schema import Plan, PlanStep


class TestPlanStep:
    def test_default_status(self):
        step = PlanStep(step_id=1, description="test")
        assert step.status == "pending"
        assert step.result is None
        assert step.error is None

    def test_custom_fields(self):
        step = PlanStep(step_id=2, description="custom", status="done", result="ok")
        assert step.step_id == 2
        assert step.status == "done"
        assert step.result == "ok"


class TestPlanCurrent:
    def test_returns_current_step(self, sample_plan):
        assert sample_plan.current().step_id == 1

    def test_returns_none_when_out_of_range(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s")], current_step=5)
        assert plan.current() is None

    def test_returns_none_for_empty_steps(self):
        plan = Plan(goal="g", steps=[])
        assert plan.current() is None


class TestPlanMarkCurrentDone:
    def test_marks_step_done_and_advances(self, sample_plan):
        sample_plan.mark_current_done("结果A")
        assert sample_plan.steps[0].status == "done"
        assert sample_plan.steps[0].result == "结果A"
        assert sample_plan.current_step == 1

    def test_completes_plan_on_last_step(self, sample_plan):
        sample_plan.current_step = 2  # 最后一步
        sample_plan.mark_current_done("完成")
        assert sample_plan.status == "completed"

    def test_noop_when_no_current(self):
        plan = Plan(goal="g", steps=[], current_step=0)
        plan.mark_current_done("x")  # 不应报错


class TestPlanMarkCurrentFailed:
    def test_marks_step_failed(self, sample_plan):
        sample_plan.mark_current_failed("出错了")
        assert sample_plan.steps[0].status == "failed"
        assert sample_plan.steps[0].error == "出错了"
        assert sample_plan.current_step == 0  # 不前进


class TestPlanToDisplay:
    def test_contains_goal_and_status(self, sample_plan):
        display = sample_plan.to_display()
        assert "测试目标" in display
        assert "active" in display

    def test_marks_current_step(self, sample_plan):
        display = sample_plan.to_display()
        assert "<-- 当前" in display

    def test_shows_reflection(self, sample_plan):
        sample_plan.reflection = "需要调整"
        display = sample_plan.to_display()
        assert "需要调整" in display

    def test_shows_done_status(self, sample_plan):
        sample_plan.steps[0].status = "done"
        sample_plan.steps[0].result = "完成"
        display = sample_plan.to_display()
        assert "[x]" in display
        assert "完成" in display


class TestPlanSerialization:
    def test_roundtrip(self, sample_plan):
        data = sample_plan.model_dump()
        restored = Plan(**data)
        assert restored.goal == sample_plan.goal
        assert len(restored.steps) == len(sample_plan.steps)
        assert restored.current_step == sample_plan.current_step
