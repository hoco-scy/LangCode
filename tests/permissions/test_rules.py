"""permissions.rules — RuleEngine 测试"""

import json
import pytest
import tempfile
from pathlib import Path

from LangCode.permissions.rules import RuleEngine, PermissionRule
from LangCode.permissions.model import PermissionResult


@pytest.fixture
def engine():
    return RuleEngine()


class TestPermissionRule:
    def test_create_rule(self):
        r = PermissionRule(source="user", tool_pattern="execute_shell", behavior="ask")
        assert r.source == "user"
        assert r.tool_pattern == "execute_shell"
        assert r.behavior == "ask"

    def test_rule_with_content(self):
        r = PermissionRule(source="project", tool_pattern="execute_shell",
                           behavior="allow", rule_content="git push*")
        assert r.rule_content == "git push*"


class TestRuleEngine:
    def test_empty_rules_default_behavior(self, engine):
        result = engine.evaluate("read_file", {}, mode="default")
        assert result.behavior == "allow"  # read_file is read-only in default mode

    def test_empty_rules_write_needs_confirm(self, engine):
        result = engine.evaluate("write_file", {}, mode="default")
        assert result.behavior == "ask"

    def test_plan_mode_blocks_writes(self, engine):
        result = engine.evaluate("write_file", {}, mode="plan")
        assert result.behavior == "deny"

    def test_plan_mode_allows_reads(self, engine):
        result = engine.evaluate("read_file", {}, mode="plan")
        assert result.behavior == "allow"

    def test_bypass_mode_allows_all(self, engine):
        result = engine.evaluate("execute_shell", {}, mode="bypass")
        assert result.behavior == "allow"

    def test_dont_ask_mode_denies_writes(self, engine):
        result = engine.evaluate("write_file", {}, mode="dont_ask")
        assert result.behavior == "deny"

    def test_dont_ask_mode_allows_reads(self, engine):
        result = engine.evaluate("read_file", {}, mode="dont_ask")
        assert result.behavior == "allow"

    def test_accept_edits_allows_writes(self, engine):
        result = engine.evaluate("write_file", {}, mode="accept_edits")
        assert result.behavior == "allow"

    def test_accept_edits_asks_for_shell(self, engine):
        result = engine.evaluate("execute_shell", {}, mode="accept_edits")
        assert result.behavior == "ask"


class TestRuleMatching:
    def test_tool_pattern_exact_match(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="execute_shell", behavior="allow"))
        result = engine.evaluate("execute_shell", {}, mode="default")
        assert result.behavior == "allow"
        assert "user" in result.reason

    def test_tool_pattern_no_match(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="execute_shell", behavior="allow"))
        result = engine.evaluate("write_file", {}, mode="default")
        assert result.behavior == "ask"  # falls back to default

    def test_wildcard_pattern(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="*", behavior="allow"))
        result = engine.evaluate("any_tool", {}, mode="default")
        assert result.behavior == "allow"

    def test_content_pattern_match(self, engine):
        engine.add_rule(PermissionRule(
            source="user", tool_pattern="execute_shell",
            behavior="allow", rule_content="git push*"
        ))
        result = engine.evaluate("execute_shell", {"command": "git push origin main"}, mode="default")
        assert result.behavior == "allow"

    def test_content_pattern_no_match(self, engine):
        engine.add_rule(PermissionRule(
            source="user", tool_pattern="execute_shell",
            behavior="allow", rule_content="git push*"
        ))
        result = engine.evaluate("execute_shell", {"command": "rm -rf /"}, mode="default")
        assert result.behavior == "ask"  # falls back to default

    def test_priority_policy_over_user(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="execute_shell", behavior="allow"))
        engine.add_rule(PermissionRule(source="policy", tool_pattern="execute_shell", behavior="deny"))
        result = engine.evaluate("execute_shell", {}, mode="default")
        assert result.behavior == "deny"

    def test_priority_project_over_user(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="execute_shell", behavior="allow"))
        engine.add_rule(PermissionRule(source="project", tool_pattern="execute_shell", behavior="deny"))
        result = engine.evaluate("execute_shell", {}, mode="default")
        assert result.behavior == "deny"


class TestLoadRules:
    def test_load_from_file(self, tmp_path):
        config = {
            "permissions": {
                "rules": [
                    {"tool": "execute_shell", "behavior": "allow"},
                    {"tool": "write_file", "pattern": "*.py", "behavior": "deny"},
                ]
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        engine = RuleEngine()
        engine._load_from_file(config_file, source="user")
        assert len(engine._rules) == 2

    def test_load_nonexistent_file(self):
        engine = RuleEngine()
        engine._load_from_file(Path("/nonexistent/config.json"), source="user")
        assert len(engine._rules) == 0

    def test_load_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")

        engine = RuleEngine()
        engine._load_from_file(bad_file, source="user")
        assert len(engine._rules) == 0


class TestGetRulesForDisplay:
    def test_empty(self, engine):
        assert engine.get_rules_for_display() == []

    def test_with_rules(self, engine):
        engine.add_rule(PermissionRule(source="user", tool_pattern="execute_shell", behavior="allow"))
        display = engine.get_rules_for_display()
        assert len(display) == 1
        assert display[0]["source"] == "user"
        assert display[0]["tool"] == "execute_shell"
