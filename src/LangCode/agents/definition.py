"""AgentDefinition — 声明式 Agent 定义。

参考 Claude Code agent 系统设计：
- BaseAgentDefinition 统一基类型
- 工具约束通过 tools/disallowedTools 声明（而非提示词）
- 模型可继承 ("inherit") 或降级
- omit_claude_md 省 Token（搜索类 Agent）

LangCode 的 Agent 定义通过代码实例化（而非 Markdown frontmatter 解析），
但结构与 Claude Code 对齐。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentDefinition:
    """Agent 声明式定义。

    agent_type: 唯一标识（"explore", "review", 或用户自定义名）
    description: 人可读描述
    when_to_use: LLM 何时应使用此 Agent 的描述（注入 supervisor 提示词）
    tools: 允许的工具列表（"*" 表示全部）
    disallowed_tools: 禁止的工具列表
    model: "inherit" | "haiku" | 具体模型名
    omit_claude_md: True 则不注入项目上下文（节省 Token）
    """
    agent_type: str
    description: str
    when_to_use: str = ""

    # ── 提示词 ──
    system_prompt: str = ""
    prompt_file: str = ""

    # ── 工具约束 ──
    tools: list[str] = field(default_factory=lambda: ["*"])
    disallowed_tools: list[str] = field(default_factory=list)

    # ── 执行配置 ──
    model: str = "inherit"
    permission_mode: str = "inherit"
    max_turns: int = 50
    omit_claude_md: bool = False
    source: str = "builtin"

    def get_system_prompt(self) -> str:
        """获取系统提示词（从 prompt_file 加载或返回内置）"""
        if self.system_prompt:
            return self.system_prompt
        if self.prompt_file:
            try:
                from pathlib import Path
                prompt_path = Path(__file__).parent.parent / "resources" / "prompts" / self.prompt_file
                if prompt_path.exists():
                    return prompt_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return ""


# ── 内置 Agent 定义 ──

EXPLORE_AGENT = AgentDefinition(
    agent_type="explore",
    description="快速代码搜索 Agent：搜索文件、阅读代码、分析结构",
    when_to_use=(
        "用于需要跨多个文件搜索、阅读和分析的任务。"
        "例如：查找特定代码模式、理解项目结构、分析代码变更历史。"
    ),
    tools=[
        "read_file", "search_files", "grep_content", "fetch_api",
        "execute_shell", "memory_search", "memory_list",
    ],
    disallowed_tools=[
        "write_file", "edit_file", "run_python",
        "delegate_explore", "delegate_review", "plan_create",
        "ast_rename", "ast_add_param", "ast_add_method", "ast_add_import",
    ],
    model="inherit",
    max_turns=30,
    omit_claude_md=True,
    source="builtin",
)

REVIEW_AGENT = AgentDefinition(
    agent_type="review",
    description="代码审查 Agent：审查质量、安全性、发现 bug、提供建议",
    when_to_use=(
        "用于代码审查、安全分析、质量评估。"
        "例如：审查 PR、分析安全性、检查代码风格。"
    ),
    tools=[
        "read_file", "search_files", "grep_content", "execute_shell", "run_python",
        "memory_search", "memory_list",
    ],
    disallowed_tools=[
        "write_file", "edit_file",
        "delegate_explore", "delegate_review", "plan_create",
        "ast_rename", "ast_add_param", "ast_add_method", "ast_add_import",
    ],
    model="inherit",
    max_turns=40,
    omit_claude_md=False,
    source="builtin",
)
