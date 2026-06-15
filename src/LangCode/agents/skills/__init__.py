"""agents/skills — Skill 系统。

Skill = YAML frontmatter + Markdown 正文。
发现源: .langcode/skills/*.md
执行模式: fork（子Agent）
"""

from LangCode.agents.skills.loader import SkillLoader, SkillDefinition

__all__ = ["SkillLoader", "SkillDefinition"]
