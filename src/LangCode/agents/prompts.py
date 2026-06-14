"""agents/prompts — 提示词模板加载器。

从 resources/prompts/ 目录加载 Markdown 格式的提示词模板。
支持平台特定提示词和 Agent 特定提示词。
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path

from LangCode.shared.logger import get_logger

log = get_logger("agents.prompts")


_PROMPTS_DIR = Path(__file__).parent.parent / "resources" / "prompts"


def load_prompt_file(filename: str) -> str:
    """从 resources/prompts/ 加载提示词文件。"""
    path = _PROMPTS_DIR / filename
    if not path.exists():
        log.debug("提示词文件不存在: %s", path)
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
        log.debug("加载提示词: %s (%d 字符)", path, len(content))
        return content
    except Exception as e:
        log.warning("加载提示词失败: %s: %s", path, e)
        return ""


def get_platform_prompt() -> str:
    """生成平台级 system prompt。

    优先从 resources/prompts/platform_*.md 加载，
    如果文件不存在则动态生成。
    """
    os_name = _platform.system().lower()
    if os_name == "darwin":
        os_name = "mac"

    # 尝试从文件加载
    content = load_prompt_file(f"platform_{os_name}.md")
    if content:
        return content

    # 动态生成（向后兼容）
    return f"""你是一个专业的 AI 编程助手，名字叫做 LangCode。

## 运行环境
- 操作系统: {os_name}
- Python 版本: {_platform.python_version()}

## 安全准则
- 执行 shell 命令前，确认命令对用户系统是安全的
- 涉及删除、覆盖等不可逆操作时，先向用户确认
- 不要执行可能损害系统的命令
"""
