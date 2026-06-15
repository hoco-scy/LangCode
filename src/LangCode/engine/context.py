"""engine.context — 系统提示组装流水线。

参考 Claude Code fetchSystemPromptParts:
  多源拼接: base prompt + platform + CLAUDE.md + memory + plan + custom

层次结构:
  1. base.md             — 基础角色 + 安全准则 + 工具使用规则
  2. platform_xxx.md     — 操作系统/Shell 类型特定信息
  3. CLAUDE.md           — 项目说明（workspace 根目录下）
  4. custom_prompt       — 用户自定义追加
  5. (plan_context)      — 由 planning.context.build_plan_context 注入（紧跟系统提示词之后）
  6. (memory_context)    — 由 Supervisor._call_llm 注入（在计划上下文之后）
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("engine.context")


def build_system_prompt(
    workspace_dir: str,
    platform: Optional[str] = None,
    custom_prompt: str = "",
) -> str:
    """组装最终的系统提示词。

    多源按顺序拼接。
    memory 和 plan 的注入在 Supervisor._call_llm 中单独处理
    （因为它们在每轮变化，需要在 LLM 调用前动态注入）。

    Args:
        workspace_dir: 项目根目录
        platform: 操作系统（windows/linux/mac），None 时自动检测
        custom_prompt: 用户自定义追加提示词

    Returns:
        完整的系统提示词字符串
    """
    parts: list[str] = []

    # 1. 基础提示词
    parts.append(_base_prompt())

    # 2. 平台特定信息
    if platform is None:
        os_name = _platform.system().lower()
        if os_name == "darwin":
            os_name = "mac"
        platform = os_name
    parts.append(_platform_prompt(platform))

    # 3. CLAUDE.md（项目说明）
    claude_md = _find_claude_md(workspace_dir)
    if claude_md:
        parts.append(f"## 项目说明\n\n{claude_md}")

    # 4. 自定义追加
    if custom_prompt:
        parts.append(f"## 自定义指令\n\n{custom_prompt}")

    return "\n\n---\n\n".join(parts)


def _base_prompt() -> str:
    """基础角色提示词。"""
    return """你是一个专业的 AI 编程助手，名字叫做 LangCode。

## 行为准则
- 回答简洁准确，必要时附上代码示例
- 每次工具调用应有明确目的，避免无意义的重复调用
- 当用户表达偏好或做出重要决策时，使用 memory_save 记住
- 执行 shell 命令前，确认命令对用户系统是安全的
- 涉及删除、覆盖等不可逆操作时，先向用户确认

## 工具使用优先级
1. 结构化代码修改 → ast_rename / ast_add_param（最安全）
2. 精确替换 → edit_file（较安全）
3. 新建/覆盖 → write_file（破坏性操作，谨慎使用）
4. Shell 命令 → execute_shell（最后手段，需确认安全性）"""


def _platform_prompt(platform: str) -> str:
    """平台特定信息。"""
    py_ver = _platform.python_version()
    return f"""## 运行环境
- 操作系统: {platform}
- Python 版本: {py_ver}
- Shell: {('PowerShell' if platform == 'windows' else 'Bash')}"""


def _find_claude_md(workspace_dir: str) -> Optional[str]:
    """在 workspace 根目录下查找 CLAUDE.md。

    向上查找最多 3 层目录。
    """
    current = Path(workspace_dir)
    for _ in range(3):
        claude_md = current / "CLAUDE.md"
        if claude_md.exists():
            try:
                content = claude_md.read_text(encoding="utf-8").strip()
                if content:
                    log.debug("找到 CLAUDE.md: %s", claude_md)
                    return content
            except Exception as e:
                log.warning("读取 CLAUDE.md 失败: %s", e)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
