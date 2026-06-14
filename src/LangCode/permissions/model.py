"""权限模型 — 五层模式 + 三元决策。

参考 Claude Code PermissionMode 设计。
LangCode v1 只有 plan/build 两层，v2 扩展到五层。
"""

from __future__ import annotations

from typing import Literal, Optional


# 五层权限模式
# 参考 Claude Code EXTERNAL_PERMISSION_MODES
PermissionMode = Literal[
    "plan",           # 只规划不执行：仅只读工具
    "accept_edits",   # 文件编辑自动通过，shell 需确认
    "default",        # 只读自动通过，写操作需确认（默认）
    "dont_ask",       # 遇到需确认的操作自动拒绝
    "bypass",         # 全部自动批准
]


class PermissionResult:
    """权限检查结果。

    参考 Claude Code PermissionResult:
    - allow(): 允许执行，无需确认
    - deny(): 拒绝执行
    - ask(): 需要用户确认

    每个工具的 check_permissions() 返回此类型。
    权限系统的全局规则也返回此类型。
    """

    __slots__ = ("behavior", "reason", "requires_user_confirmation")

    def __init__(
        self,
        behavior: str,
        reason: str = "",
        requires_user_confirmation: bool = False,
    ):
        self.behavior = behavior
        self.reason = reason
        self.requires_user_confirmation = requires_user_confirmation

    def __repr__(self):
        return f"PermissionResult({self.behavior!r}, reason={self.reason!r})"

    @classmethod
    def allow(cls, reason: str = "") -> PermissionResult:
        """允许执行。"""
        return cls(behavior="allow", reason=reason)

    @classmethod
    def deny(cls, reason: str) -> PermissionResult:
        """拒绝执行。"""
        return cls(behavior="deny", reason=reason, requires_user_confirmation=False)

    @classmethod
    def ask(cls, reason: str = "") -> PermissionResult:
        """需要用户确认。"""
        return cls(behavior="ask", reason=reason, requires_user_confirmation=True)


# ── PermissionMode 相关辅助 ──

# plan 模式允许的工具名集合（只读工具）
# 参考 Claude Code plan 模式下可用工具
PLAN_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "search_files",
    "fetch_api",
    "memory_search",
    "memory_list",
    "plan_create",
    "delegate_explore",
    "delegate_review",
    "ast_info",
    "ast_find",
})


def is_read_only_mode(mode: str) -> bool:
    """判断当前模式是否为只读。"""
    return mode == "plan"


def default_behavior_for_mode(mode: str, tool_name: str) -> PermissionResult:
    """根据权限模式和工具名返回默认行为。

    这是在没有匹配任何规则时的兜底逻辑。
    """
    if mode == "plan":
        if tool_name in PLAN_MODE_ALLOWED_TOOLS:
            return PermissionResult.allow("plan mode: read-only tool allowed")
        return PermissionResult.deny(f"plan 模式禁止使用 {tool_name}")

    if mode == "accept_edits":
        if tool_name in ("execute_shell", "run_python"):
            return PermissionResult.ask(f"accept_edits 模式: {tool_name} 需确认")
        return PermissionResult.allow("accept_edits 模式: allowed")

    if mode == "dont_ask":
        if tool_name in ("execute_shell", "run_python", "write_file", "edit_file"):
            return PermissionResult.deny(f"dont_ask 模式: 自动拒绝 {tool_name}")
        return PermissionResult.allow("dont_ask 模式: read-only allowed")

    if mode == "bypass":
        return PermissionResult.allow("bypass 模式: 全部允许")

    # default 模式
    if tool_name in ("read_file", "search_files", "fetch_api",
                      "memory_search", "memory_list", "plan_create",
                      "ast_info", "ast_find"):
        return PermissionResult.allow("default 模式: 只读工具允许")
    return PermissionResult.ask(f"default 模式: {tool_name} 需确认")
