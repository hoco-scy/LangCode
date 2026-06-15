"""agents.skills.loader — Skill 加载器。

从 .langcode/skills/*.md 加载自定义 Skill 定义。

文件格式（参考 Claude Code Skill 系统）：
```markdown
---
name: code-review
description: "审查代码变更"
tools: [read_file, search_files, execute_shell]
model: inherit
---

你是一个代码审查专家...
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("agents.skills.loader")


@dataclass
class SkillDefinition:
    """Skill 定义。"""
    name: str
    description: str
    prompt: str                      # Markdown 正文（Skill 提示词）
    allowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    context: str = "fork"            # "fork" (子Agent) | "inline" (注入)
    source_file: str = ""


class SkillLoader:
    """从 .langcode/skills/*.md 和包内 resources/prompts/skills/*.md 加载 Skill。

    用法：
        loader = SkillLoader("/path/to/workspace")
        skills = loader.load_all()
        for skill in skills:
            print(f"{skill.name}: {skill.description}")
    """

    # 包内内置 Skill 目录
    _BUILTIN_DIR = Path(__file__).parent.parent.parent / "resources" / "prompts" / "skills"

    def __init__(self, workspace_dir: str):
        self.skills_dir = Path(workspace_dir) / ".langcode" / "skills"

    def load_all(self) -> list[SkillDefinition]:
        """加载所有 Skill 文件（内置 + 工作区自定义）。"""
        seen: set[str] = set()
        skills: list[SkillDefinition] = []

        # 内置 Skill
        for skill in self._load_dir(self._BUILTIN_DIR):
            skills.append(skill)
            seen.add(skill.name)

        # 工作区自定义 Skill（同名覆盖内置）
        for skill in self._load_dir(self.skills_dir):
            if skill.name in seen:
                # 替换同名内置
                skills = [s for s in skills if s.name != skill.name]
            skills.append(skill)
            seen.add(skill.name)

        log.info("已加载 %d 个 Skill", len(skills))
        return skills

    def _load_dir(self, directory: Path) -> list[SkillDefinition]:
        """从指定目录加载 Skill 文件。"""
        if not directory.exists():
            return []
        results: list[SkillDefinition] = []
        for md_file in sorted(directory.glob("*.md")):
            skill = self._load_one(md_file)
            if skill:
                results.append(skill)
        return results

    def _load_one(self, path: Path) -> Optional[SkillDefinition]:
        """加载单个 Skill 文件。"""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("读取 Skill 失败: %s — %s", path, e)
            return None

        # 解析 YAML frontmatter
        frontmatter, body = _parse_frontmatter(content)

        name = frontmatter.get("name", path.stem)
        description = frontmatter.get("description", "")
        tools = frontmatter.get("tools", [])
        model = frontmatter.get("model", "inherit")

        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",")]

        return SkillDefinition(
            name=name,
            description=description,
            prompt=body.strip(),
            allowed_tools=tools,
            model=model,
            source_file=str(path),
        )


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter + Markdown 正文。

    Returns:
        (frontmatter_dict, body_text)
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    yaml_text = parts[1].strip()
    body = parts[2].strip()

    # 简单 YAML 解析（避免依赖 PyYAML）
    frontmatter: dict = {}
    for line in yaml_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value.startswith("[") and value.endswith("]"):
                # 简单列表解析
                value = [v.strip().strip('"').strip("'")
                         for v in value[1:-1].split(",") if v.strip()]
            frontmatter[key] = value

    return frontmatter, body
