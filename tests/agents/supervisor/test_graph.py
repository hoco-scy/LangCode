"""agents/supervisor/graph.py — 混合范式路由函数测试"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.constants import END

from LangCode.agents.supervisor.graph import (
    _increment_retry,
    _unified_agent_routing,
    _after_tools_routing,
    _step_inject,
    _plan_create_routing,
    _reflect_routing,
    SupervisorAgent,
)
from LangCode.agents.supervisor.router import MAX_SUPERVISOR_ITERATIONS
from LangCode.planning.schema import Plan, PlanStep


class TestIncrementRetry:
    def test_increments_from_zero(self):
        assert _increment_retry({"tool_retry_count": 0}) == {"tool_retry_count": 1}

    def test_defaults_to_zero(self):
        assert _increment_retry({}) == {"tool_retry_count": 1}


class TestUnifiedAgentRouting:
    """统一路由：agent 响应后的路由决策"""

    def test_tool_calls_goes_to_tools(self, ai_tool_message):
        state = {"messages": [ai_tool_message], "current_plan": None}
        assert _unified_agent_routing(state) == "mode_tools"

    def test_plan_steps_goes_to_plan_create(self):
        msg = AIMessage(content="计划：\n1. A\n2. B")
        state = {"messages": [msg], "current_plan": None, "route": "plan", "plan_steps": ["A", "B"]}
        assert _unified_agent_routing(state) == "plan_create"

    def test_delegate_code_route(self):
        msg = AIMessage(content="[route: code task: 写代码]")
        state = {"messages": [msg], "current_plan": None, "route": "code"}
        assert _unified_agent_routing(state) == "delegate"

    def test_delegate_research_route(self):
        msg = AIMessage(content="")
        state = {"messages": [msg], "current_plan": None, "route": "research"}
        assert _unified_agent_routing(state) == "delegate"

    def test_in_plan_execution_goes_to_reflector(self, ai_plain_message, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        state = {"messages": [ai_plain_message], "current_plan": sample_plan.model_dump()}
        assert _unified_agent_routing(state) == "reflector"

    def test_no_signals_goes_to_end(self, ai_plain_message):
        state = {"messages": [ai_plain_message], "current_plan": None, "route": "end"}
        assert _unified_agent_routing(state) == END

    def test_completed_plan_goes_to_end(self, ai_plain_message, sample_plan):
        sample_plan.status = "completed"
        state = {"messages": [ai_plain_message], "current_plan": sample_plan.model_dump()}
        assert _unified_agent_routing(state) == END


class TestAfterToolsRouting:
    def test_plan_step_in_progress_goes_to_reflector(self, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        state = {"current_plan": sample_plan.model_dump()}
        assert _after_tools_routing(state) == "reflector"

    def test_no_plan_goes_to_agent(self):
        state = {"current_plan": None}
        assert _after_tools_routing(state) == "agent"

    def test_completed_plan_goes_to_agent(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _after_tools_routing(state) == "agent"


class TestPlanCreateRouting:
    def test_active_plan_goes_to_step_inject(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_create_routing(state) == "step_inject"

    def test_no_plan_goes_to_end(self):
        state = {"current_plan": None}
        assert _plan_create_routing(state) == END


class TestReflectRouting:
    def test_more_steps_goes_to_step_inject(self, sample_plan):
        sample_plan.steps[0].status = "done"
        sample_plan.current_step = 1
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_routing(state) == "step_inject"

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


class TestStepInject:
    def test_injects_step_prompt(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump(), "messages": []}
        result = _step_inject(state)
        assert len(result["messages"]) == 1
        assert "第 1/3" in result["messages"][0].content

    def test_no_plan_returns_empty(self):
        assert _step_inject({"current_plan": None}) == {}

    def test_all_done_returns_empty(self, sample_plan):
        sample_plan.current_step = len(sample_plan.steps)
        assert _step_inject({"current_plan": sample_plan.model_dump()}) == {}


class TestInjectContext:
    def _make_agent(self):
        from unittest.mock import MagicMock
        return SupervisorAgent(llm=MagicMock(), sys_checkpoint=None, sys_tools=[])

    def test_injects_active_plan(self):
        agent = self._make_agent()
        plan = Plan(goal="X", steps=[PlanStep(step_id=1, description="Y")])
        result = agent._inject_context({"messages": [], "current_plan": plan.model_dump()})
        assert len(result) == 1
        assert "X" in result[0].content

    def test_empty_when_no_plan(self):
        assert self._make_agent()._inject_context({"messages": [], "current_plan": None}) == []


class TestGetAgentPrompt:
    def test_returns_string(self):
        assert isinstance(SupervisorAgent.get_agent_prompt(), str)
        assert len(SupervisorAgent.get_agent_prompt()) > 100
