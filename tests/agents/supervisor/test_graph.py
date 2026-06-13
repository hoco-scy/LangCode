"""agents/supervisor/graph.py — 路由纯函数测试"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.constants import END

from LangCode.shared.routing import should_use_tools
from LangCode.agents.supervisor.graph import (
    _increment_retry,
    _should_plan,
    _plan_or_end,
    _after_step,
    SupervisorAgent,
)
from LangCode.planning.schema import Plan, PlanStep


class TestShouldUseTools:
    def test_tool_calls_returns_tools(self, ai_tool_message):
        state = {"messages": [HumanMessage(content="hi"), ai_tool_message]}
        assert should_use_tools(state) == "tools"

    def test_plain_message_returns_end(self, ai_plain_message):
        state = {"messages": [HumanMessage(content="hi"), ai_plain_message]}
        assert should_use_tools(state) == END


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


class TestShouldPlan:
    def test_no_plan_returns_react(self):
        state = {"current_plan": None}
        assert _should_plan(state) == "react"

    def test_active_plan_with_pending_steps(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump()}
        assert _should_plan(state) == "step_executor"

    def test_completed_plan_returns_react(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _should_plan(state) == "react"

    def test_invalid_plan_returns_react(self):
        state = {"current_plan": {"invalid": True}}
        assert _should_plan(state) == "react"


class TestPlanOrEnd:
    def test_no_plan_returns_end(self):
        state = {"current_plan": None}
        assert _plan_or_end(state) == END

    def test_completed_plan_returns_end(self, sample_plan):
        sample_plan.status = "completed"
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_or_end(state) == END

    def test_abandoned_plan_returns_end(self, sample_plan):
        sample_plan.status = "abandoned"
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_or_end(state) == END

    def test_active_plan_with_pending_steps(self, sample_plan):
        state = {"current_plan": sample_plan.model_dump()}
        assert _plan_or_end(state) == "step_executor"

    def test_active_plan_all_done(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="done")])
        state = {"current_plan": plan.model_dump()}
        assert _plan_or_end(state) == END


class TestAfterStep:
    def test_tool_calls_returns_agent(self, ai_tool_message):
        state = {"messages": [ai_tool_message]}
        assert _after_step(state) == "agent"

    def test_plain_message_returns_reflector(self, ai_plain_message):
        state = {"messages": [ai_plain_message]}
        assert _after_step(state) == "reflector"


class TestGetAgentPrompt:
    def test_returns_nonempty_string(self):
        prompt = SupervisorAgent.get_agent_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "ReAct" in prompt


class TestInjectContext:
    def _make_agent(self):
        from unittest.mock import MagicMock
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        return SupervisorAgent(llm=mock_llm, sys_checkpoint=None, sys_tools=[])

    def test_returns_empty_when_no_plan(self):
        agent = self._make_agent()
        state = {"messages": [], "current_plan": None}
        assert agent._inject_context(state) == []

    def test_returns_empty_when_plan_completed(self):
        from LangCode.planning.schema import Plan, PlanStep
        agent = self._make_agent()
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="done")], status="completed")
        state = {"messages": [], "current_plan": plan.model_dump()}
        assert agent._inject_context(state) == []

    def test_injects_plan_summary_when_active(self):
        from LangCode.planning.schema import Plan, PlanStep
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
