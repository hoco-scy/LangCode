"""engine.context — 系统提示组装测试"""

import pytest
import tempfile
from pathlib import Path

from LangCode.engine.context import build_system_prompt, _find_claude_md, _platform_prompt


class TestBuildSystemPrompt:
    def test_contains_base_prompt(self):
        prompt = build_system_prompt(workspace_dir="/tmp")
        assert "LangCode" in prompt
        assert "行为准则" in prompt

    def test_contains_platform(self):
        prompt = build_system_prompt(workspace_dir="/tmp", platform="windows")
        assert "windows" in prompt.lower()

    def test_contains_custom_prompt(self):
        prompt = build_system_prompt(workspace_dir="/tmp", custom_prompt="Be concise.")
        assert "Be concise." in prompt

    def test_finds_claude_md(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# My Project\nThis is a test project.")
        prompt = build_system_prompt(workspace_dir=str(tmp_path))
        assert "My Project" in prompt

    def test_no_claude_md(self, tmp_path):
        prompt = build_system_prompt(workspace_dir=str(tmp_path))
        assert "项目说明" not in prompt or "My Project" not in prompt


class TestPlatformPrompt:
    def test_windows(self):
        p = _platform_prompt("windows")
        assert "windows" in p.lower()
        assert "PowerShell" in p

    def test_linux(self):
        p = _platform_prompt("linux")
        assert "linux" in p.lower()
        assert "Bash" in p

    def test_mac(self):
        p = _platform_prompt("mac")
        assert "mac" in p.lower()


class TestFindClaudeMd:
    def test_finds_in_same_dir(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("test content")
        result = _find_claude_md(str(tmp_path))
        assert result == "test content"

    def test_finds_in_parent_dir(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("parent content")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = _find_claude_md(str(subdir))
        assert result == "parent content"

    def test_returns_none_when_not_found(self, tmp_path):
        result = _find_claude_md(str(tmp_path))
        assert result is None

    def test_ignores_empty_file(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("")
        result = _find_claude_md(str(tmp_path))
        assert result is None
