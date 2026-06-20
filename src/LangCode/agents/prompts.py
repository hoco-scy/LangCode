"""agents/prompts — 提示词模板加载器。

从 resources/prompts/ 目录加载 Markdown 格式的提示词模板。
支持平台特定提示词和 Agent 特定提示词。
Windows 平台模板支持 Jinja2 条件渲染（检测 bash 可用性）。
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


def get_platform_prompt(bash_path: str | None = None) -> str:
    """生成平台级 system prompt。

    优先从 resources/prompts/platform_*.md 加载。
    如果文件包含 Jinja2 模板标记，会尝试渲染（Windows 平台）。
    如果文件不存在则动态生成。

    Args:
        bash_path: bash 可执行文件路径（由 main.py 传入，消除 L2→L3 依赖）。
                   Windows 平台用于判断使用 bash 还是 cmd.exe 语法。
    """
    os_name = _platform.system().lower()
    if os_name == "darwin":
        os_name = "mac"

    # 尝试从文件加载
    content = load_prompt_file(f"platform_{os_name}.md")
    if content:
        # Jinja2 模板渲染（Windows 平台检测 bash）
        if os_name == "windows" and ("{%" in content or "{{" in content):
            content = _render_windows_prompt(content, bash_path)
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


def _render_windows_prompt(template: str, bash_path: str | None) -> str:
    """渲染 Windows 平台模板。

    使用 bash_path 参数（由 main.py 传入）判断使用 bash 还是 cmd.exe。
    使用简单的字符串替换而非引入 Jinja2 依赖。
    """
    if bash_path:
        # bash 可用 → 渲染 {% if bash_path %} 分支
        block, _ = _extract_jinja_block(template, "if bash_path", "else", "endif")
        if block:
            return block.strip()
    else:
        # cmd.exe → 渲染 {% else %} 分支
        _, block = _extract_jinja_block(template, "else", "endif", "endif")
        if block:
            # 去掉 {% else %} 行本身
            return block.strip()

    return template


def _extract_jinja_block(
    template: str, start_tag: str, end_tag: str, close_tag: str
) -> tuple[str, str]:
    """从 Jinja2 模板中提取指定条件块。

    Returns:
        (before_block, block_content) — 匹配到的块内容
    """
    import re

    pattern = rf'\{{\%\s*{start_tag}\s*\%\}}(.*?)\{{\%\s*{end_tag}\s*\%\}}'
    match = re.search(pattern, template, re.DOTALL)
    if match:
        return match.group(0), match.group(1)
    return "", ""
