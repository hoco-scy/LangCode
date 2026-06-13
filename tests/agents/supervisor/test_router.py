"""agents/supervisor/router.py — 工具驱动路由测试"""

from langchain_core.messages import AIMessage

from LangCode.agents.supervisor.router import (
    process_tool_results, after_tools_routing,
    _is_newly_created_plan, _is_step_in_progress,
    MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.planning.schema import Plan, PlanStep


class TestProcessToolResults:
    """从 AI tool_calls 中提取 plan 和 delegate 信号"""

    def test_plan_create_tool_call(self):
        msg = AIMessage(content="", tool_calls=[{
            "name": "plan_create",
            "args": {"goal": "重构模块", "steps": ["分析代码", "编写实现", "运行测试"]},
            "id": "tc1",
        }])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert "current_plan" in result
        plan = Plan(**result["current_plan"])
        assert plan.goal == "重构模块"
        assert len(plan.steps) == 3
        assert result["agent_mode"] == "build"

    def test_delegate_code_tool_call(self):
        msg = AIMessage(content="", tool_calls=[{
            "name": "delegate_code",
            "args": {"task": "写 hello world"},
            "id": "tc2",
        }])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert result["route"] == "code"
        assert result["task_description"] == "写 hello world"

    def test_delegate_research_tool_call(self):
        msg = AIMessage(content="", tool_calls=[{
            "name": "delegate_research",
            "args": {"task": "分析代码结构"},
            "id": "tc3",
        }])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert result["route"] == "research"

    def test_delegate_review_tool_call(self):
        msg = AIMessage(content="", tool_calls=[{
            "name": "delegate_review",
            "args": {"task": "审查安全性"},
            "id": "tc4",
        }])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert result["route"] == "review"

    def test_normal_tool_call_no_signal(self):
        msg = AIMessage(content="", tool_calls=[{
            "name": "read_file",
            "args": {"file_path": "test.py"},
            "id": "tc5",
        }])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert result == {}

    def test_plan_and_delegate_combined(self):
        """一个 tool_calls 中同时包含 plan_create 和其他工具"""
        msg = AIMessage(content="", tool_calls=[
            {"name": "plan_create", "args": {"goal": "X", "steps": ["A", "B"]}, "id": "tc1"},
            {"name": "read_file", "args": {"file_path": "x.py"}, "id": "tc2"},
        ])
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert "current_plan" in result

    def test_no_tool_calls(self):
        msg = AIMessage(content="直接回复")
        state = {"messages": [msg]}
        result = process_tool_results(state)
        assert result == {}

    def test_empty_messages(self):
        state = {"messages": []}
        result = process_tool_results(state)
        assert result == {}


class TestAfterToolsRouting:
    """mode_tools + process_tool_results 后路由"""

    def test_newly_created_plan_goes_to_mark_step(self, sample_plan):
        """刚创建的计划（所有步骤 pending）→ mark_step"""
        state = {"messages": [], "current_plan": sample_plan.model_dump(), "route": ""}
        assert after_tools_routing(state) == "mark_step"

    def test_delegate_goes_to_delegate(self):
        state = {"messages": [], "current_plan": None, "route": "code"}
        assert after_tools_routing(state) == "delegate"

    def test_delegate_research(self):
        state = {"messages": [], "current_plan": None, "route": "research"}
        assert after_tools_routing(state) == "delegate"

    def test_plan_step_in_progress_goes_to_reflector(self, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        state = {"messages": [], "current_plan": sample_plan.model_dump(), "route": ""}
        assert after_tools_routing(state) == "reflector"

    def test_no_signals_goes_to_agent(self):
        state = {"messages": [], "current_plan": None, "route": ""}
        assert after_tools_routing(state) == "agent"

    def test_completed_plan_goes_to_agent(self, sample_plan):
        sample_plan.status = "completed"
        state = {"messages": [], "current_plan": sample_plan.model_dump(), "route": ""}
        assert after_tools_routing(state) == "agent"


class TestIsNewlyCreatedPlan:
    def test_all_pending(self, sample_plan):
        assert _is_newly_created_plan(sample_plan.model_dump()) is True

    def test_step_in_progress(self, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        assert _is_newly_created_plan(sample_plan.model_dump()) is False

    def test_completed_plan(self, sample_plan):
        sample_plan.status = "completed"
        assert _is_newly_created_plan(sample_plan.model_dump()) is False

    def test_single_step_plan(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s")])
        assert _is_newly_created_plan(plan.model_dump()) is False

    def test_invalid_data(self):
        assert _is_newly_created_plan({}) is False


class TestIsStepInProgress:
    def test_in_progress(self, sample_plan):
        sample_plan.steps[0].status = "in_progress"
        assert _is_step_in_progress(sample_plan.model_dump()) is True

    def test_all_pending(self, sample_plan):
        assert _is_step_in_progress(sample_plan.model_dump()) is False

    def test_completed_plan(self, sample_plan):
        sample_plan.status = "completed"
        assert _is_step_in_progress(sample_plan.model_dump()) is False

    def test_invalid_data(self):
        assert _is_step_in_progress({}) is False
