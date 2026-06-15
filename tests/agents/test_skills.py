"""agents.skills — SkillLoader 测试"""

import pytest
from pathlib import Path
from unittest.mock import patch

from LangCode.agents.skills.loader import SkillLoader, SkillDefinition, _parse_frontmatter


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        content = "Just some text without frontmatter"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_basic_frontmatter(self):
        content = "---\nname: test\ndescription: \"A test skill\"\n---\n\nBody content"
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "test"
        assert fm["description"] == "A test skill"
        assert body == "Body content"

    def test_frontmatter_with_list(self):
        content = "---\ntools: [read_file, search_files]\n---\n\nPrompt"
        fm, body = _parse_frontmatter(content)
        assert fm["tools"] == ["read_file", "search_files"]

    def test_frontmatter_with_single_quotes(self):
        content = "---\nname: 'my-skill'\n---\n\nBody"
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "my-skill"

    def test_empty_frontmatter(self):
        content = "---\n---\n\nBody"
        fm, body = _parse_frontmatter(content)
        assert fm == {}

    def test_comments_ignored(self):
        content = "---\n# This is a comment\nname: test\n---\n\nBody"
        fm, body = _parse_frontmatter(content)
        assert "name" in fm


class TestSkillLoader:
    @pytest.fixture(autouse=True)
    def _no_builtin(self, tmp_path):
        """隔离内置 Skill 目录，确保测试只看到自己创建的文件。"""
        empty = tmp_path / "_no_builtin"
        with patch.object(SkillLoader, "_BUILTIN_DIR", empty):
            yield

    def test_no_skills_dir(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills == []

    def test_empty_skills_dir(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills == []

    def test_load_single_skill(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        skill_file = skills_dir / "test-skill.md"
        skill_file.write_text(
            "---\nname: test-skill\ndescription: \"A test\"\ntools: [read_file]\n---\n\nYou are a test.",
            encoding="utf-8",
        )

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].description == "A test"
        assert skills[0].allowed_tools == ["read_file"]
        assert skills[0].prompt == "You are a test."

    def test_load_multiple_skills(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)

        (skills_dir / "a-skill.md").write_text("---\nname: a\n---\n\nPrompt A", encoding="utf-8")
        (skills_dir / "b-skill.md").write_text("---\nname: b\n---\n\nPrompt B", encoding="utf-8")

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 2

    def test_non_md_files_ignored(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "not-a-skill.txt").write_text("ignored", encoding="utf-8")
        (skills_dir / "a-skill.md").write_text("---\nname: a\n---\n\nPrompt", encoding="utf-8")

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1

    def test_skill_defaults(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "minimal.md").write_text("No frontmatter prompt", encoding="utf-8")

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "minimal"  # defaults to filename stem
        assert skills[0].allowed_tools == []
        assert skills[0].model == "inherit"

    def test_skill_model_field(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skill.md").write_text(
            "---\nname: test\nmodel: haiku\n---\n\nPrompt",
            encoding="utf-8",
        )

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills[0].model == "haiku"

    def test_source_file_recorded(self, tmp_path):
        skills_dir = tmp_path / ".langcode" / "skills"
        skills_dir.mkdir(parents=True)
        skill_file = skills_dir / "test.md"
        skill_file.write_text("---\nname: test\n---\n\nPrompt", encoding="utf-8")

        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert str(skill_file) == skills[0].source_file


class TestSkillDefinition:
    def test_create(self):
        sd = SkillDefinition(
            name="test",
            description="desc",
            prompt="prompt",
            allowed_tools=["read_file"],
        )
        assert sd.name == "test"
        assert sd.context == "fork"  # default

    def test_defaults(self):
        sd = SkillDefinition(name="x", description="", prompt="")
        assert sd.allowed_tools == []
        assert sd.model == "inherit"
        assert sd.source_file == ""
