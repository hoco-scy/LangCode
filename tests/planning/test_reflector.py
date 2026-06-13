"""planning/reflector.py — should_continue_plan 纯函数 + reflect_node mock 测试"""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from LangCode.planning.reflector import should_continue_plan, reflect_node, ReflectDecision
from LangCode.planning.schema import Plan, PlanStep


# ============================================================
#  should_continue_plan 纯函数测试
# ============================================================

class TestShouldContinuePlan:
    def test_no_plan_returns_end(self):
        state = {"current_plan": None}
        assert should_continue_plan(state) == "end"

    def test_completed_plan_returns_end(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="done")], status="completed")
        state = {"current_plan": plan.model_dump()}
        assert should_continue_plan(state) == "end"

    def test_abandoned_plan_returns_end(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s")], status="abandoned")
        state = {"current_plan": plan.model_dump()}
        assert should_continue_plan(state) == "end"

    def test_pending_step_returns_execute(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s")])
        state = {"current_plan": plan.model_dump()}
        assert should_continue_plan(state) == "execute"

    def test_in_progress_step_returns_execute(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s", status="in_progress")])
        state = {"current_plan": plan.model_dump()}
        assert should_continue_plan(state) == "execute"

    def test_reflection_needing_adjustment_returns_replan(self):
        plan = Plan(goal="g", steps=[PlanStep(step_id=1, description="s")], reflection="需要调整: xxx")
        state = {"current_plan": plan.model_dump()}
        assert should_continue_plan(state) == "replan"


# ============================================================
#  reflect_node mock LLM 测试（使用 structured output）
# ============================================================

class TestReflectNode:
    def _make_state(self, plan):
        return {
            "messages": [HumanMessage(content="test")],
            "current_plan": plan.model_dump(),
        }

    def _mock_llm(self, action, reason="ok", step_summary="", adjustment=""):
        """模拟 with_structured_output 返回 ReflectDecision"""
        llm = MagicMock()
        decision = ReflectDecision(
            action=action, reason=reason,
            step_summary=step_summary, adjustment=adjustment,
        )
        structured = MagicMock()
        structured.invoke.return_value = decision
        llm.with_structured_output.return_value = structured
        return llm

    def test_continue_marks_done(self, sample_plan):
        state = self._make_state(sample_plan)
        llm = self._mock_llm("continue", "成功", step_summary="文件已创建")
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "done"
        assert plan.current_step == 1
        assert "文件已创建" in plan.steps[0].result

    def test_retry_marks_failed_then_in_progress(self, sample_plan):
        state = self._make_state(sample_plan)
        llm = self._mock_llm("retry", "需要重试")
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "in_progress"

    def test_skip_marks_skipped(self, sample_plan):
        state = self._make_state(sample_plan)
        llm = self._mock_llm("skip", "跳过")
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "skipped"

    def test_replan_sets_reflection(self, sample_plan):
        llm = self._mock_llm("replan", "", adjustment="改方案")
        state = self._make_state(sample_plan)
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert "改方案" in plan.reflection

    def test_no_plan_returns_empty(self):
        state = {"messages": [], "current_plan": None}
        result = reflect_node(state, MagicMock())
        assert result == {}

    def test_structured_output_exception_defaults_continue(self, sample_plan):
        """structured output 调用异常时，默认标记完成继续"""
        state = self._make_state(sample_plan)
        llm = MagicMock()
        structured = MagicMock()
        structured.invoke.side_effect = Exception("LLM error")
        llm.with_structured_output.return_value = structured
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].status == "done"

    def test_step_summary_used_as_result(self, sample_plan):
        """step_summary 应写入步骤结果"""
        state = self._make_state(sample_plan)
        llm = self._mock_llm("continue", "ok", step_summary="读取了3个文件")
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].result == "读取了3个文件"

    def test_step_summary_fallback_to_reason(self, sample_plan):
        """step_summary 为空时回退到 reason"""
        state = self._make_state(sample_plan)
        llm = self._mock_llm("continue", "操作完成", step_summary="")
        result = reflect_node(state, llm)
        plan = Plan(**result["current_plan"])
        assert plan.steps[0].result == "操作完成"
