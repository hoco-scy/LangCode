"""shared.types — LCState v2 结构测试"""

import pytest

from LangCode.shared.types import LCState, _last_wins


class TestLCState:
    def test_v2_fields(self):
        """验证 v2 最终版字段集合"""
        fields = set(LCState.__annotations__.keys())
        expected = {
            "messages", "route", "current_plan", "task_description",
            "verify_errors", "memory_context", "supervisor_iterations",
            "_processed_tool_ids", "_pending_delegations",
        }
        assert fields == expected, f"多余字段: {fields - expected}, 缺少字段: {expected - fields}"

    def test_no_deprecated_fields(self):
        """确认 DEPRECATED 字段已被移除"""
        fields = set(LCState.__annotations__.keys())
        deprecated = {
            "user_name", "platform", "tool_retry_count", "current_agent",
            "agent_mode", "dangerous_edit_mode", "strict_mode",
            "content_generation_count", "tool_calls_count", "code_generation_count",
            "plan_step_index", "plan_steps",
        }
        overlap = fields & deprecated
        assert overlap == set(), f"发现 DEPRECATED 字段: {overlap}"


class TestLastWinsReducer:
    def test_takes_new_value(self):
        assert _last_wins("old", "new") == "new"

    def test_takes_new_int(self):
        assert _last_wins(1, 2) == 2

    def test_takes_new_none(self):
        assert _last_wins("something", None) is None

    def test_takes_new_list(self):
        old = [1, 2]
        new = [3, 4]
        assert _last_wins(old, new) == [3, 4]
