"""permissions.model — 权限模型测试"""

import pytest
from LangCode.permissions.model import (
    PermissionResult,
    is_read_only_mode,
    default_behavior_for_mode,
    PLAN_MODE_ALLOWED_TOOLS,
)


class TestPermissionResult:
    def test_allow(self):
        r = PermissionResult.allow("read-only ok")
        assert r.behavior == "allow"
        assert r.requires_user_confirmation is False

    def test_deny(self):
        r = PermissionResult.deny("not allowed")
        assert r.behavior == "deny"
        assert r.requires_user_confirmation is False

    def test_ask(self):
        r = PermissionResult.ask("need confirm")
        assert r.behavior == "ask"
        assert r.requires_user_confirmation is True

    def test_repr(self):
        r = PermissionResult.allow("test")
        assert "allow" in repr(r)


class TestIsReadOnlyMode:
    def test_plan_is_readonly(self):
        assert is_read_only_mode("plan") is True

    def test_default_not_readonly(self):
        assert is_read_only_mode("default") is False

    def test_bypass_not_readonly(self):
        assert is_read_only_mode("bypass") is False


class TestDefaultBehavior:
    def test_plan_allows_read_file(self):
        r = default_behavior_for_mode("plan", "read_file")
        assert r.behavior == "allow"

    def test_plan_denies_write_file(self):
        r = default_behavior_for_mode("plan", "write_file")
        assert r.behavior == "deny"

    def test_plan_denies_shell(self):
        r = default_behavior_for_mode("plan", "execute_shell")
        assert r.behavior == "deny"

    def test_accept_edits_allows_edit_file(self):
        r = default_behavior_for_mode("accept_edits", "edit_file")
        assert r.behavior == "allow"

    def test_accept_edits_asks_shell(self):
        r = default_behavior_for_mode("accept_edits", "execute_shell")
        assert r.behavior == "ask"

    def test_dont_ask_deny_write(self):
        r = default_behavior_for_mode("dont_ask", "write_file")
        assert r.behavior == "deny"

    def test_bypass_allows_all(self):
        r = default_behavior_for_mode("bypass", "execute_shell")
        assert r.behavior == "allow"

    def test_default_asks_write(self):
        r = default_behavior_for_mode("default", "write_file")
        assert r.behavior == "ask"

    def test_default_allows_read(self):
        r = default_behavior_for_mode("default", "read_file")
        assert r.behavior == "allow"

    def test_plan_allowed_tools_set(self):
        """plan 模式允许的工具应该全部在 PLAN_MODE_ALLOWED_TOOLS 中"""
        for tool_name in ["read_file", "search_files", "fetch_api",
                          "memory_search", "memory_list",
                          "write_todo", "update_todo", "modify_todo"]:
            assert tool_name in PLAN_MODE_ALLOWED_TOOLS
