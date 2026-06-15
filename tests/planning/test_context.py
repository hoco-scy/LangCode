"""planning.context — 计划上下文注入测试（v3: build_plan_context）"""

import pytest

from LangCode.planning.context import build_plan_context
from LangCode.planning.schema import Plan, PlanStep


def _make_plan_dict(status="active", step_status="in_progress", n_steps=3):
    steps = [
        PlanStep(step_id=i+1, description=f"step {i+1}", status=step_status if i == 0 else "pending")
        for i in range(n_steps)
    ]
    plan = Plan(goal="test goal", steps=steps, status=status)
    return plan.model_dump()


class TestBuildPlanContext:
    def test_none_returns_none(self):
        assert build_plan_context(None) is None

    def test_empty_dict_returns_none(self):
        assert build_plan_context({}) is None

    def test_active_plan_returns_string(self):
        plan_data = _make_plan_dict(step_status="in_progress")
        result = build_plan_context(plan_data)
        assert isinstance(result, str)
        assert "执行计划" in result
        assert "test goal" in result

    def test_contains_all_steps(self):
        plan_data = _make_plan_dict(n_steps=3)
        result = build_plan_context(plan_data)
        assert "step 1" in result
        assert "step 2" in result
        assert "step 3" in result

    def test_contains_execution_rules(self):
        plan_data = _make_plan_dict()
        result = build_plan_context(plan_data)
        assert "update_todo" in result
        assert "modify_todo" in result
        assert "执行规则" in result

    def test_contains_current_step_marker(self):
        plan_data = _make_plan_dict()
        result = build_plan_context(plan_data)
        assert "← 当前" in result

    def test_completed_plan_returns_none(self):
        plan_data = _make_plan_dict(status="completed")
        assert build_plan_context(plan_data) is None

    def test_abandoned_plan_returns_none(self):
        plan_data = _make_plan_dict(status="abandoned")
        assert build_plan_context(plan_data) is None

    def test_progress_counter(self):
        plan_data = _make_plan_dict(n_steps=4)
        result = build_plan_context(plan_data)
        assert "0/4" in result

    def test_done_step_shown(self):
        steps = [
            PlanStep(step_id=1, description="s1", status="done", result="完成了"),
            PlanStep(step_id=2, description="s2", status="in_progress"),
        ]
        plan = Plan(goal="test", steps=steps)
        result = build_plan_context(plan.model_dump())
        assert "[x]" in result
        assert "完成了" in result
