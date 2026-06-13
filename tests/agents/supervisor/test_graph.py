"""agents/supervisor/graph.py — Agent-as-Entry 架构路由函数测试"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.constants import END

from LangCode.agents.supervisor.graph import (
    _increment_retry,
    _agent_routing,
    _after_tools,
    _step_inject,
    _plan_ready,
    _reflect_done,
    SupervisorAgent,
)
from LangCode.agents.supervisor.router import MAX_SUPERVISOR_ITERATIONS
from LangCode.planning.schema import Plan, PlanStep


class TestIncrementRetry:
    def test_increments_from_zero(self):
        state = {"tool_retry_count": 0}
        assert _increment_retry(state) == {"tool_retry_count": 1}

    def test_increments_from_existing(self):
        state = {"tool_retry_count": 5}
        assert _increment_retry(state) == {"tool_retry_count": 6}

    def test_defaults_to_zero(self):
        state = {}
        assert _increment_retry(state) == {"tool_retry_count": 1}


class TestAgentRouting:
    def test_tool_calls_goes_to_mode_tools(self, ai_tool_message):
        state = {"messages": [ai_tool_message], "current_plan": None}
        assert _agent_routing(state) == "mode_tools"

    def test_no_tool_calls_no_plan_goes_to_end(self, ai_plain_message):
        """react 路径完成 → 直接 END"""
        state = {"messages": [ai_plain_message], "current_plan": None}
        assert _agent_routing(state) == END

    def test_no_tool_calls_with_active_plan_goes_to_reflector(self, ai_plain_message, sample_plan):
        """plan 执行中，agent 给出纯文本回复 → reflector"""
        sample_plan.steps[0].status = "in_progress"
        state = {"messages": [ai_plain_message], "current_plan": sample_plan.model_dump()}
        assert _agent_routing(state) == "reflector"

    def test_no_tool_calls_completed_plan_goes_to_end(self, ai_plain_message, sample_plan):
        sample_plan.status = "completed"
        state = {"messages": [ai_plain_message], "current_plan": sample_plan.model_dump()}
        assert _agent_routing(state) == END


class TestAfterTools:
    def test_normal_iteration_goes_to_agent(self):
        state = {"supervisor_iterations": 1}
        assert _after_tools(state) == "agent"

    def test_iteration_limit_goes_to_end(self):
        state = {"supervisor_iterations": MAX_SUPERVISOR_ITERATIONS + 1}
        assert _after_tools(state) == "__end__"


class TestPlanReady:
    def test_no_plan_goes_to_end(self):
        state = {"current_plan": None}
        assert _plan_ready(state) == END

    def test_active_plan_with_pending_steps(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_ready(state) == "step_inject"

    def test_completed_plan_goes_to_end(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_ready(state) == END

    def test_invalid_plan_goes_to_end(self):
        state = {"current_plan": {"invalid": True}}
        assert _plan_ready(state) == END


class TestReflectDone:
    def test_completed_plan_goes_to_end(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_done(state) == END

    def test_abandoned_plan_goes_to_end(self, sample_plan):
        sample_plan.status = "abandoned"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_done(state) == END

    def test_active_plan_with_pending_steps(self, sample_plan):
        sample_plan.steps[0].status = "done"
        sample_plan.current_step = 1
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_done(state) == "step_inject"

    def test_needs_adjustment_goes_to_end(self, sample_plan):
        sample_plan.reflection = "需要调整: 修改步骤"
        state = {"current_plan": sample_plan.model_dump()}
        assert _reflect_done(state) == END


class TestStepInject:
    def test_injects_step_prompt(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump(), "messages": []}
        result = _step_inject(state)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], SystemMessage)
        assert "第 1" in result["messages"][0].content
        assert result["current_plan"]["steps"][0]["status"] == "in_progress"

    def test_no_plan_returns_empty(self):
        state = {"current_plan": None, "messages": []}
        result = _step_inject(state)
        assert result == {}

    def test_all_steps_done_returns_empty(self, sample_plan):
        for step in sample_plan.steps:
            step.status = "done"
        sample_plan.status = "completed"
        sample_plan.current_step = len(sample_plan.steps)
        state = {"current_plan": sample_plan.model_dump(), "messages": []}
        result = _step_inject(state)
        assert result.get("messages") in (None, [], {})


class TestGetAgentPrompt:
    def test_returns_nonempty_string(self):
        prompt = SupervisorAgent.get_agent_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100


class TestInjectContext:
    def _make_agent(self):
        from unittest.mock import MagicMock
        mock_llm = MagicMock()
        return SupervisorAgent(llm=mock_llm, sys_checkpoint=None, sys_tools=[])

    def test_returns_empty_when_no_plan(self):
        agent = self._make_agent()
        state = {"messages": [], "current_plan": None}
        assert agent._inject_context(state) == []

    def test_injects_plan_summary_when_active(self):
        from langchain_core.messages import SystemMessage
        agent = self._make_agent()
        plan = Plan(goal="重构模块", steps=[PlanStep(step_id=1, description="分析代码")])
        state = {"messages": [], "current_plan": plan.model_dump()}
        result = agent._inject_context(state)
        assert len(result) == 1
        assert isinstance(result[0], SystemMessage)
        assert "重构模块" in result[0].content

    def test_returns_empty_on_invalid_plan(self):
        agent = self._make_agent()
        state = {"messages": [], "current_plan": {"invalid": True}}
        assert agent._inject_context(state) == []
