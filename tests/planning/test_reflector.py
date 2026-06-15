"""planning.reflector — 反思节点测试"""

import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from LangCode.planning.reflector import (
    ReflectDecision, reflect_decision, reflect_node, should_continue_plan,
    REFLECT_PROMPT,
)
from LangCode.planning.schema import Plan, PlanStep


def _make_state(plan_dict=None, messages=None):
    state = {
        "messages": messages or [HumanMessage(content="test")],
        "current_plan": plan_dict,
        "route": "",
        "task_description": "",
        "verify_errors": None,
        "memory_context": "",
        "supervisor_iterations": 0,
    }
    return state


def _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress"):
    steps = []
    for i in range(n_steps):
        if i < current_step:
            s = PlanStep(step_id=i+1, description=f"step {i+1}", status="done", result="ok")
        elif i == current_step:
            s = PlanStep(step_id=i+1, description=f"step {i+1}", status=step_status)
        else:
            s = PlanStep(step_id=i+1, description=f"step {i+1}", status="pending")
        steps.append(s)
    plan = Plan(goal="test goal", steps=steps, current_step=current_step)
    return plan.model_dump()


class TestReflectDecision:
    def test_create(self):
        d = ReflectDecision(action="continue", reason="ok", step_summary="did stuff")
        assert d.action == "continue"
        assert d.step_summary == "did stuff"

    def test_valid_actions(self):
        for action in ("continue", "retry", "skip", "replan"):
            d = ReflectDecision(action=action, reason="test")
            assert d.action == action

    def test_defaults(self):
        d = ReflectDecision(action="continue", reason="ok")
        assert d.step_summary == ""
        assert d.adjustment == ""


class TestReflectNode:
    def test_no_plan_returns_empty(self):
        state = _make_state(plan_dict=None)
        result = reflect_node(state, MagicMock())
        assert result == {}

    def test_continue_marks_done(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_tc = {
            "name": "reflect_decision",
            "args": {"action": "continue", "reason": "ok", "step_summary": "completed step"},
            "id": "tc_1",
        }
        mock_response.tool_calls = [mock_tc]
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        result = reflect_node(state, mock_llm)

        updated_plan = Plan(**result["current_plan"])
        assert updated_plan.steps[0].status == "done"
        assert updated_plan.steps[0].result == "completed step"

    def test_retry_keeps_in_progress(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_tc = {
            "name": "reflect_decision",
            "args": {"action": "retry", "reason": "failed"},
            "id": "tc_1",
        }
        mock_response.tool_calls = [mock_tc]
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        result = reflect_node(state, mock_llm)

        updated_plan = Plan(**result["current_plan"])
        assert updated_plan.steps[0].status == "in_progress"

    def test_skip_advances_step(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_tc = {
            "name": "reflect_decision",
            "args": {"action": "skip", "reason": "impossible"},
            "id": "tc_1",
        }
        mock_response.tool_calls = [mock_tc]
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        result = reflect_node(state, mock_llm)

        updated_plan = Plan(**result["current_plan"])
        assert updated_plan.steps[0].status == "skipped"

    def test_no_tool_call_defaults_to_done(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.tool_calls = []
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        result = reflect_node(state, mock_llm)

        updated_plan = Plan(**result["current_plan"])
        assert updated_plan.steps[0].status == "done"

    def test_llm_exception_defaults_to_done(self):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.side_effect = Exception("API error")

        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        result = reflect_node(state, mock_llm)

        updated_plan = Plan(**result["current_plan"])
        assert updated_plan.steps[0].status == "done"


class TestShouldContinuePlan:
    def test_no_plan_returns_end(self):
        state = _make_state(plan_dict=None)
        assert should_continue_plan(state) == "end"

    def test_completed_returns_end(self):
        plan_dict = _make_plan_dict(n_steps=1, current_step=0)
        plan = Plan(**plan_dict)
        plan.mark_current_done("ok")
        state = _make_state(plan_dict=plan.model_dump())
        assert should_continue_plan(state) == "end"

    def test_abandoned_returns_end(self):
        plan = Plan(goal="x", steps=[PlanStep(step_id=1, description="s")], status="abandoned")
        state = _make_state(plan_dict=plan.model_dump())
        assert should_continue_plan(state) == "end"

    def test_active_step_returns_execute(self):
        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="in_progress")
        state = _make_state(plan_dict=plan_dict)
        assert should_continue_plan(state) == "execute"

    def test_pending_step_returns_execute(self):
        plan_dict = _make_plan_dict(n_steps=3, current_step=0, step_status="pending")
        state = _make_state(plan_dict=plan_dict)
        assert should_continue_plan(state) == "execute"
