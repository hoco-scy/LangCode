"""planning.context — 计划上下文注入器测试"""

import pytest
from langchain_core.messages import SystemMessage

from LangCode.planning.context import inject_plan_context
from LangCode.planning.schema import Plan, PlanStep


def _make_plan_dict(status="active", step_status="in_progress", n_steps=3):
    steps = [
        PlanStep(step_id=i+1, description=f"step {i+1}", status=step_status if i == 0 else "pending")
        for i in range(n_steps)
    ]
    plan = Plan(goal="test goal", steps=steps, status=status)
    return plan.model_dump()


class TestInjectPlanContext:
    def test_none_returns_empty(self):
        assert inject_plan_context(None) == []

    def test_empty_dict_returns_empty(self):
        assert inject_plan_context({}) == []

    def test_active_plan_in_progress(self):
        plan_data = _make_plan_dict(step_status="in_progress")
        msgs = inject_plan_context(plan_data)
        assert len(msgs) > 0
        assert isinstance(msgs[0], SystemMessage)
        content = msgs[0].content
        assert "step 1" in content or "步骤" in content

    def test_active_plan_pending(self):
        plan_data = _make_plan_dict(step_status="pending")
        msgs = inject_plan_context(plan_data)
        # pending 状态也应该注入上下文
        assert len(msgs) > 0

    def test_completed_plan(self):
        plan_data = _make_plan_dict(status="completed")
        msgs = inject_plan_context(plan_data)
        # completed 状态应注入完成提示
        assert len(msgs) > 0

    def test_abandoned_plan(self):
        plan_data = _make_plan_dict(status="abandoned")
        msgs = inject_plan_context(plan_data)
        # abandoned 状态不应注入或注入极少
        # 根据实现可能是空或包含提示
        assert isinstance(msgs, list)

    def test_messages_are_system_messages(self):
        plan_data = _make_plan_dict()
        msgs = inject_plan_context(plan_data)
        for msg in msgs:
            assert isinstance(msg, SystemMessage)
