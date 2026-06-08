"""planning/tools.py — plan_create + plan_show 测试"""

from LangCode.planning.tools import plan_create, plan_show


class TestPlanCreate:
    def test_creates_plan_successfully(self):
        result = plan_create.invoke({"goal": "测试", "steps": ["步骤A", "步骤B"]})
        assert result["success"] is True
        assert result["plan"]["goal"] == "测试"
        assert len(result["plan"]["steps"]) == 2
        assert result["plan"]["steps"][0]["description"] == "步骤A"
        assert "display" in result

    def test_empty_steps(self):
        result = plan_create.invoke({"goal": "空", "steps": []})
        assert result["success"] is True
        assert len(result["plan"]["steps"]) == 0


class TestPlanShow:
    def test_returns_static_message(self):
        result = plan_show.invoke({})
        assert result["success"] is True
        assert "message" in result
