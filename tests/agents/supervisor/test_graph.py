"""agents/supervisor/graph.py — 工具驱动路由图测试"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.constants import END

from LangCode.agents.supervisor.graph import (
    _mark_step_in_progress,
    _reflect_routing,
    SupervisorAgent,
)
from LangCode.agents.supervisor.router import MAX_SUPERVISOR_ITERATIONS
from LangCode.planning.schema import Plan, PlanStep


class TestMarkStepInProgress:
    def test_marks_pending_step_to_in_progress(self, sample_plan):
        """新建计划后，第一个步骤应从 pending 变为 in_progress"""
        state = {"current_plan": sample_plan.model_dump()}
        result = _mark_step_in_progress(state)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "in_progress"

    def test_no_plan_returns_empty(self):
        assert _mark_step_in_progress({"current_plan": None}) == {}

    def test_already_in_progress_no_change(self, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        state = {"current_plan": sample_plan.model_dump()}
        result = _mark_step_in_progress(state)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "in_progress"

    def test_all_done_returns_empty(self, sample_plan):
        sample_plan.current_step = len(sample_plan.steps)
        result = _mark_step_in_progress({"current_plan": sample_plan.model_dump()})
        assert result == {}


class TestReflectRouting:
    def test_more_steps_goes_to_mark_step(self, sample_plan):
        sample_plan.steps[0].status = "done"
        sample_plan.current_step = 1
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_routing(state) == "mark_step"

    def test_completed_plan_goes_to_end(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_routing(state) == END

    def test_abandoned_plan_goes_to_end(self, sample_plan):
        sample_plan.status = "abandoned"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_routing(state) == END

    def test_needs_adjustment_goes_to_end(self, sample_plan):
        sample_plan.reflection = "需要调整: 修改步骤"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_routing(state) == END

    def test_all_steps_done_goes_to_end(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="done")])
        plan.current_step = 1
        state = {"current_plan": plan.model_dump()}
        assert _reflect_routing(state) == END


class TestInjectContext:
    def _make_agent(self):
        from unittest.mock import MagicMock
        return SupervisorAgent(llm=MagicMock(), sys_checkpoint=None, sys_tools=[])

    def test_injects_step_execution_prompt(self):
        """有 in_progress 步骤时注入执行指令"""
        agent = self._make_agent()
        plan = Plan(goal="X", steps=[
            PlanStep(step_id=1, description="Y", status="in_progress")
        ])
        result = agent._inject_context({"messages": [], "current_plan": plan.model_dump()})
        assert len(result) == 1
        assert "执行计划" in result[0].content
        assert "第 1 步" in result[0].content

    def test_injects_pending_step_prompt(self):
        """有 pending 步骤时注入下一步提示"""
        agent = self._make_agent()
        plan = Plan(goal="X", steps=[
            PlanStep(step_id=1, description="Y")
        ])
        result = agent._inject_context({"messages": [], "current_plan": plan.model_dump()})
        assert len(result) == 1
        assert "下一步" in result[0].content

    def test_empty_when_no_plan(self):
        assert self._make_agent()._inject_context({"messages": [], "current_plan": None}) == []

    def test_empty_when_plan_completed(self):
        plan = Plan(goal="X", steps=[], status="completed")
        assert self._make_agent()._inject_context({
            "messages": [], "current_plan": plan.model_dump()
        }) == []


class TestGetAgentPrompt:
    def test_returns_string(self):
        assert isinstance(SupervisorAgent.get_agent_prompt(), str)
        assert len(SupervisorAgent.get_agent_prompt()) > 100
