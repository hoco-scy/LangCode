"""planning/tools.py — plan_create 测试"""

import json
from langgraph.types import Command

from LangCode.planning.tools import plan_create


class TestPlanCreate:
    def test_creates_plan_successfully(self):
        result = plan_create.invoke({"goal": "测试", "steps": ["步骤A", "步骤B"], "tool_call_id": "tc1"})
        assert isinstance(result, Command)
        # ToolMessage 包含结果 JSON
        tool_msg = result.update["messages"][0]
        data = json.loads(tool_msg.content)
        assert data["success"] is True
        assert data["plan"]["goal"] == "测试"
        assert len(data["plan"]["steps"]) == 2
        # 图状态更新
        assert result.update["current_plan"]["goal"] == "测试"
        assert result.update["plan_step_index"] == 0
        assert result.update["task_description"] == "测试"

    def test_empty_steps(self):
        result = plan_create.invoke({"goal": "空", "steps": [], "tool_call_id": "tc2"})
        assert isinstance(result, Command)
        data = json.loads(result.update["messages"][0].content)
        assert data["success"] is True
        assert len(data["plan"]["steps"]) == 0
