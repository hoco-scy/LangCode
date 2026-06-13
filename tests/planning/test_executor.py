"""planning/executor.py — execute_step_node 测试"""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from LangCode.planning.executor import execute_step_node
from LangCode.planning.schema import Plan, PlanStep


class TestExecuteStepNode:
    def _make_plan_dict(self, step_status="pending"):
        plan = Plan(
            goal="测试目标",
            steps=[PlanStep(step_id=1, description="步骤一", status=step_status)]
        )
        return plan.model_dump()

    def test_no_plan_returns_empty(self):
        llm = MagicMock()
        state = {"messages": [], "current_plan": None}
        result = execute_step_node(state, llm)
        assert result == {}

    def test_no_current_step_returns_plan(self):
        llm = MagicMock()
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="done")])
        state = {"messages": [], "current_plan": plan.model_dump()}
        result = execute_step_node(state, llm)
        assert "current_plan" in result

    def test_executes_step_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="步骤完成")
        state = {
            "messages": [HumanMessage(content="hi")],
            "current_plan": self._make_plan_dict(),
        }
        result = execute_step_node(state, mock_llm)
        assert "messages" in result
        assert "current_plan" in result
        mock_llm.invoke.assert_called_once()

    def test_marks_step_done_on_text_response(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="已完成")
        state = {
            "messages": [HumanMessage(content="hi")],
            "current_plan": self._make_plan_dict(),
        }
        result = execute_step_node(state, mock_llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "done"

    def test_preserves_tool_calls(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "args": {"file_path": "x.py"}, "id": "tc1"}]
        )
        state = {
            "messages": [HumanMessage(content="hi")],
            "current_plan": self._make_plan_dict(),
        }
        result = execute_step_node(state, mock_llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "in_progress"

    def test_injects_plan_context_into_messages(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="done")
        state = {
            "messages": [HumanMessage(content="hi")],
            "current_plan": self._make_plan_dict(),
        }
        execute_step_node(state, mock_llm)
        called_messages = mock_llm.invoke.call_args[0][0]
        all_content = " ".join(m.content for m in called_messages if hasattr(m, 'content'))
        assert "步骤一" in all_content
