"""tools.builtin.delegate — 子Agent 委派工具测试"""

import json
import pytest

from LangCode.tools.builtin.delegate import (
    delegate_explore, delegate_review, delegate_tools,
)


class TestDelegateToolsList:
    def test_count(self):
        assert len(delegate_tools) == 2

    def test_names(self):
        names = {t.name for t in delegate_tools}
        assert names == {"delegate_explore", "delegate_review"}


class TestDelegateExplore:
    def test_returns_json(self):
        result = delegate_explore.invoke({"task": "find all Python files"})
        parsed = json.loads(result)
        assert parsed["agent"] == "explore"
        assert parsed["task"] == "find all Python files"
        assert parsed["status"] == "delegated"

    def test_preserves_chinese(self):
        result = delegate_explore.invoke({"task": "查找所有 Python 文件"})
        parsed = json.loads(result)
        assert parsed["task"] == "查找所有 Python 文件"

    def test_empty_task(self):
        result = delegate_explore.invoke({"task": ""})
        parsed = json.loads(result)
        assert parsed["agent"] == "explore"
        assert parsed["task"] == ""


class TestDelegateReview:
    def test_returns_json(self):
        result = delegate_review.invoke({"task": "review security"})
        parsed = json.loads(result)
        assert parsed["agent"] == "review"
        assert parsed["task"] == "review security"
        assert parsed["status"] == "delegated"

    def test_long_task(self):
        long_task = "x" * 5000
        result = delegate_review.invoke({"task": long_task})
        parsed = json.loads(result)
        assert len(parsed["task"]) == 5000


class TestDelegateSchema:
    def test_explore_schema(self):
        schema = delegate_explore.args_schema.model_json_schema()
        assert "task" in schema["properties"]

    def test_review_schema(self):
        schema = delegate_review.args_schema.model_json_schema()
        assert "task" in schema["properties"]
