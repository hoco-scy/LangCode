"""agents.prompts — 提示词加载器测试"""

import pytest
from unittest.mock import patch

from LangCode.agents.prompts import (
    load_prompt_file,
    get_platform_prompt,
    _render_windows_prompt,
    _extract_jinja_block,
)


class TestLoadPromptFile:
    def test_load_existing_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# 测试提示词\n内容", encoding="utf-8")
        with patch("LangCode.agents.prompts._PROMPTS_DIR", tmp_path):
            result = load_prompt_file("test.md")
        assert "测试提示词" in result

    def test_nonexistent_file_returns_empty(self, tmp_path):
        with patch("LangCode.agents.prompts._PROMPTS_DIR", tmp_path):
            assert load_prompt_file("no_such_file.md") == ""


class TestGetPlatformPrompt:
    def test_returns_string(self):
        result = get_platform_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_platform_info(self):
        result = get_platform_prompt()
        # 应包含操作系统信息
        assert "操作系统" in result or "运行环境" in result or "LangCode" in result

    def test_bash_path_none_windows_uses_cmd(self):
        """Windows 平台 + bash_path=None → 应渲染 cmd.exe 分支"""
        template = "前缀\n{% if bash_path %}bash模式{% else %}cmd模式{% endif %}\n后缀"
        result = _render_windows_prompt(template, bash_path=None)
        assert "cmd模式" in result
        assert "bash模式" not in result

    def test_bash_path_set_uses_bash(self):
        """bash_path 有值 → 应渲染 bash 分支"""
        template = "前缀\n{% if bash_path %}bash模式{% else %}cmd模式{% endif %}\n后缀"
        result = _render_windows_prompt(template, bash_path="/usr/bin/bash")
        assert "bash模式" in result
        assert "cmd模式" not in result


class TestExtractJinjaBlock:
    def test_extracts_if_block(self):
        template = "before\n{% if bash_path %}content here{% endif %}\nafter"
        match, content = _extract_jinja_block(template, "if bash_path", "endif", "endif")
        assert "content here" in content

    def test_extracts_else_block(self):
        template = "{% if x %}if分支{% else %}else分支{% endif %}"
        match, content = _extract_jinja_block(template, "else", "endif", "endif")
        assert "else分支" in content

    def test_no_match_returns_empty(self):
        template = "no jinja here"
        match, content = _extract_jinja_block(template, "if x", "endif", "endif")
        assert match == ""
        assert content == ""
