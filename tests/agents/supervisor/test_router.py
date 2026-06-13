"""agents/supervisor/router.py — 中枢路由节点测试"""

from unittest.mock import MagicMock, patch

from LangCode.agents.supervisor.router import (
    SupervisorDecision, supervisor_node, supervisor_routing,
    MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.shared.state import LCState
from LangCode.planning.schema import Plan, PlanStep


class TestSupervisorDecision:
    def test_schema_fields(self):
        d = SupervisorDecision(route="react", reasoning="简单任务", mode="build")
        assert d.route == "react"
        assert d.reasoning == "简单任务"
        assert d.mode == "build"
        assert d.task == ""

    def test_delegate_fields(self):
        d = SupervisorDecision(route="code", reasoning="需要写代码", task="写hello world", mode="build")
        assert d.route == "code"
        assert d.task == "写hello world"


class TestSupervisorRouting:
    def test_react_route(self):
        state = {"route": "react", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "react"

    def test_plan_route(self):
        state = {"route": "plan", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "plan"

    def test_code_route(self):
        state = {"route": "code", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "code"

    def test_research_route(self):
        state = {"route": "research", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "research"

    def test_review_route(self):
        state = {"route": "review", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "review"

    def test_end_route(self):
        state = {"route": "end", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "end"

    def test_invalid_route_defaults_to_react(self):
        state = {"route": "invalid", "supervisor_iterations": 1}
        assert supervisor_routing(state) == "react"

    def test_missing_route_defaults_to_react(self):
        state = {"supervisor_iterations": 1}
        assert supervisor_routing(state) == "react"

    def test_iteration_limit_forces_end(self):
        state = {"route": "react", "supervisor_iterations": MAX_SUPERVISOR_ITERATIONS + 1}
        assert supervisor_routing(state) == "end"


class TestSupervisorNode:
    def _mock_llm(self, decision: SupervisorDecision):
        """创建返回指定决策的 mock LLM"""
        mock = MagicMock()
        mock.with_structured_output.return_value.invoke.return_value = decision
        return mock

    def test_react_route_with_simple_task(self):
        llm = self._mock_llm(SupervisorDecision(route="react", reasoning="简单问题", mode="build"))
        state = {
            "messages": [],
            "supervisor_iterations": 0,
            "agent_mode": "build",
        }
        result = supervisor_node(state, llm)
        assert result["route"] == "react"
        assert result["agent_mode"] == "build"
        assert result["supervisor_iterations"] == 1

    def test_plan_route_with_complex_task(self):
        llm = self._mock_llm(SupervisorDecision(route="plan", reasoning="多步骤任务", mode="plan"))
        state = {
            "messages": [],
            "supervisor_iterations": 0,
            "agent_mode": "build",
        }
        result = supervisor_node(state, llm)
        assert result["route"] == "plan"
        assert result["agent_mode"] == "plan"

    def test_delegate_sets_task_description(self):
        llm = self._mock_llm(SupervisorDecision(route="code", reasoning="需要写代码", task="写hello world"))
        state = {
            "messages": [],
            "supervisor_iterations": 0,
            "agent_mode": "build",
        }
        result = supervisor_node(state, llm)
        assert result["route"] == "code"
        assert result["task_description"] == "写hello world"

    def test_iteration_limit_forces_end(self):
        llm = self._mock_llm(SupervisorDecision(route="react", reasoning="继续"))
        state = {
            "messages": [],
            "supervisor_iterations": MAX_SUPERVISOR_ITERATIONS,
            "agent_mode": "build",
        }
        result = supervisor_node(state, llm)
        assert result["route"] == "end"

    def test_llm_failure_defaults_to_react(self):
        mock = MagicMock()
        mock.with_structured_output.return_value.invoke.side_effect = Exception("LLM 错误")
        state = {
            "messages": [],
            "supervisor_iterations": 0,
            "agent_mode": "build",
        }
        result = supervisor_node(state, mock)
        assert result["route"] == "react"
        assert result["agent_mode"] == "build"
