"""planning/planner.py — create_plan_node 测试"""

import json
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from LangCode.planning.planner import create_plan_node


class TestCreatePlanNode:
    def _make_mock_llm(self, response_content):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=response_content)
        return mock_llm

    def test_parses_valid_json(self):
        plan_json = json.dumps({
            "goal": "重构工具模块",
            "steps": [
                {"step_id": 1, "description": "分析现有代码"},
                {"step_id": 2, "description": "编写新模块"},
            ]
        })
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="重构工具模块")], "task_description": "", "memory_context": ""}
        result = create_plan_node(state, llm)
        assert result["task_description"] == "重构工具模块"
        plan = result["current_plan"]
        assert plan["goal"] == "重构工具模块"
        assert len(plan["steps"]) == 2

    def test_strips_markdown_code_block(self):
        plan_json = "```json\n" + json.dumps({
            "goal": "test",
            "steps": [{"step_id": 1, "description": "step1"}]
        }) + "\n```"
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="test")], "task_description": "", "memory_context": ""}
        result = create_plan_node(state, llm)
        assert result["current_plan"]["goal"] == "test"

    def test_fallback_on_invalid_json(self):
        llm = self._make_mock_llm("这不是 JSON")
        state = {"messages": [HumanMessage(content="某个任务")], "task_description": "", "memory_context": ""}
        result = create_plan_node(state, llm)
        plan = result["current_plan"]
        assert plan["goal"] == "某个任务"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["status"] == "in_progress"

    def test_uses_task_description_over_message(self):
        plan_json = json.dumps({
            "goal": "g",
            "steps": [{"step_id": 1, "description": "s"}]
        })
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="msg")], "task_description": "明确的任务", "memory_context": ""}
        result = create_plan_node(state, llm)
        assert result["task_description"] == "明确的任务"

    def test_extracts_task_from_last_human_message(self):
        plan_json = json.dumps({
            "goal": "g",
            "steps": [{"step_id": 1, "description": "s"}]
        })
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="用户任务")], "task_description": "", "memory_context": ""}
        result = create_plan_node(state, llm)
        assert result["task_description"] == "用户任务"

    def test_injects_memory_context(self):
        plan_json = json.dumps({
            "goal": "g",
            "steps": [{"step_id": 1, "description": "s"}]
        })
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="task")], "task_description": "", "memory_context": "之前用过 pytest"}
        create_plan_node(state, llm)
        called_messages = llm.invoke.call_args[0][0]
        all_content = " ".join(m.content for m in called_messages)
        assert "pytest" in all_content

    def test_sets_plan_step_index_to_zero(self):
        plan_json = json.dumps({
            "goal": "g",
            "steps": [{"step_id": 1, "description": "s"}]
        })
        llm = self._make_mock_llm(plan_json)
        state = {"messages": [HumanMessage(content="task")], "task_description": "", "memory_context": ""}
        result = create_plan_node(state, llm)
        assert result["plan_step_index"] == 0
