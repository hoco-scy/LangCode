"""agents.router — 路由决策测试"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from LangCode.agents.router import (
    should_use_tools,
    process_tool_results,
    after_tools_routing,
    _is_newly_created,
    _is_step_in_progress,
    _find_last_ai_with_tool_calls,
)
from LangCode.planning.schema import Plan, PlanStep


class TestShouldUseTools:
    def test_with_tool_calls(self):
        state = {"messages": [
            AIMessage(content="test", tool_calls=[{"name": "read_file", "args": {"file_path": "test.py"}, "id": "tc1"}])
        ]}
        assert should_use_tools(state) == "tools"

    def test_without_tool_calls(self):
        state = {"messages": [AIMessage(content="done")]}
        assert should_use_tools(state) == "__end__"

    def test_empty_messages(self):
        assert should_use_tools({"messages": []}) == "__end__"


class TestProcessToolResults:
    def test_plan_create(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "plan_create",
                "args": {"goal": "重构代码", "steps": ["步骤1", "步骤2"]},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert "current_plan" in updates
        plan = Plan(**updates["current_plan"])
        assert plan.goal == "重构代码"
        assert len(plan.steps) == 2

    def test_delegate_explore(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "delegate_explore",
                "args": {"task": "搜索代码模式"},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert updates["route"] == "explore"
        assert updates["task_description"] == "搜索代码模式"

    def test_delegate_review(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "delegate_review",
                "args": {"task": "审查代码"},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert updates["route"] == "review"

    def test_no_signal(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "read_file",
                "args": {"file_path": "test.py"},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert updates == {}

    def test_empty_messages(self):
        assert process_tool_results({"messages": []}) == {}


class TestAfterToolsRouting:
    def test_newly_created_plan(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="step1"),
            PlanStep(step_id=2, description="step2"),
        ])
        state = {"current_plan": plan.model_dump(), "route": ""}
        assert after_tools_routing(state) == "plan_created"

    def test_delegate_explore(self):
        state = {"current_plan": None, "route": "explore"}
        assert after_tools_routing(state) == "delegated"

    def test_delegate_review(self):
        state = {"current_plan": None, "route": "review"}
        assert after_tools_routing(state) == "delegated"

    def test_reflect_when_step_in_progress(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="step1", status="in_progress"),
            PlanStep(step_id=2, description="step2"),
        ])
        state = {"current_plan": plan.model_dump(), "route": ""}
        assert after_tools_routing(state) == "reflect"

    def test_react_default(self):
        state = {"current_plan": None, "route": ""}
        assert after_tools_routing(state) == "react"


class TestIsNewlyCreated:
    def test_newly_created(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1"),
            PlanStep(step_id=2, description="s2"),
        ])
        assert _is_newly_created(plan.model_dump()) is True

    def test_with_in_progress_step(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
            PlanStep(step_id=2, description="s2"),
        ])
        assert _is_newly_created(plan.model_dump()) is False

    def test_single_step(self):
        plan = Plan(goal="test", steps=[PlanStep(step_id=1, description="s1")])
        assert _is_newly_created(plan.model_dump()) is False


class TestIsStepInProgress:
    def test_in_progress(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        assert _is_step_in_progress(plan.model_dump()) is True

    def test_all_pending(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1"),
            PlanStep(step_id=2, description="s2"),
        ])
        assert _is_step_in_progress(plan.model_dump()) is False

    def test_no_plan(self):
        assert _is_step_in_progress(None) is False
