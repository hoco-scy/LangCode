"""planning.planner — plan_create 工具 + create_plan_node 测试"""

import json
import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, AIMessage

from LangCode.planning.planner import create_plan_tool, create_plan_node, PlanCreateInput
from LangCode.planning.schema import Plan, PlanStep


class TestPlanCreateTool:
    def test_tool_creation(self):
        tool = create_plan_tool()
        assert tool.name == "plan_create"

    def test_tool_invocation(self):
        tool = create_plan_tool()
        result = tool.invoke({
            "goal": "test goal",
            "steps": ["step 1", "step 2", "step 3"],
        })
        parsed = json.loads(result)
        assert parsed["goal"] == "test goal"
        assert parsed["total"] == 3
        assert len(parsed["steps"]) == 3

    def test_tool_schema(self):
        tool = create_plan_tool()
        schema = tool.args_schema.model_json_schema()
        assert "goal" in schema["properties"]
        assert "steps" in schema["properties"]


class TestPlanCreateInput:
    def test_valid(self):
        inp = PlanCreateInput(goal="test", steps=["a", "b"])
        assert inp.goal == "test"
        assert len(inp.steps) == 2

    def test_min_steps(self):
        with pytest.raises(Exception):
            PlanCreateInput(goal="test", steps=["only one"])

    def test_empty_goal_valid(self):
        inp = PlanCreateInput(goal="", steps=["a", "b"])
        assert inp.goal == ""


class TestCreatePlanNode:
    def test_from_task_description(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "goal": "implement feature",
            "steps": [
                {"step_id": 1, "description": "read code"},
                {"step_id": 2, "description": "write code"},
                {"step_id": 3, "description": "test"},
            ],
        })
        mock_llm.invoke.return_value = mock_response

        state = {
            "messages": [HumanMessage(content="add feature X")],
            "task_description": "implement feature X",
            "memory_context": "",
        }
        result = create_plan_node(state, mock_llm)

        assert "current_plan" in result
        plan = Plan(**result["current_plan"])
        assert plan.goal == "implement feature"
        assert len(plan.steps) == 3
        assert result["task_description"] == "implement feature X"

    def test_from_last_user_message(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "goal": "do stuff",
            "steps": [
                {"step_id": 1, "description": "a"},
                {"step_id": 2, "description": "b"},
            ],
        })
        mock_llm.invoke.return_value = mock_response

        state = {
            "messages": [HumanMessage(content="please do stuff")],
            "task_description": "",
            "memory_context": "",
        }
        result = create_plan_node(state, mock_llm)

        assert "current_plan" in result

    def test_json_parse_failure_returns_fallback(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "not valid json"
        mock_llm.invoke.return_value = mock_response

        state = {
            "messages": [HumanMessage(content="test")],
            "task_description": "test task",
            "memory_context": "",
        }
        result = create_plan_node(state, mock_llm)

        assert "current_plan" in result
        plan = Plan(**result["current_plan"])
        assert len(plan.steps) == 1
        assert plan.steps[0].status == "in_progress"
