"""permissions.rules — 三层优先级规则匹配引擎。

参考 Claude Code 权限规则系统:
  - 多个来源: policy > project > user（由 SettingsSource 层级决定）
  - 工具匹配: toolName 精确匹配 + ruleContent 内容级匹配
  - 扁平化: 所有来源的 allow/deny/ask 规则分别扁平化

规则格式（在 .langcode/config.json 的 permissions.rules 数组中）:
  {
    "tool": "execute_shell" | "write_file" | "*",
    "pattern": "git push*",  // 可选，内容级匹配
    "behavior": "allow" | "deny" | "ask"
  }
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Optional

from LangCode.permissions.model import (
    PermissionMode, PermissionResult, default_behavior_for_mode,
)
from LangCode.shared.logger import get_logger

log = get_logger("permissions.rules")


@dataclass
class PermissionRule:
    """单条权限规则。"""
    source: str          # "policy" | "project" | "user"
    tool_pattern: str    # "execute_shell" | "write_file" | "*" | "execute_shell(git:*)"
    behavior: str        # "allow" | "deny" | "ask"
    rule_content: str = ""  # 内容级匹配模式（如 "git push*"）


# 来源优先级（数字越小优先级越高）
_SOURCE_PRIORITY = {"policy": 0, "project": 1, "user": 2}


class RuleEngine:
    """权限规则匹配引擎。

    评估流程：
    1. 按优先级排序规则（policy > project > user）
    2. 逐条匹配（工具名精确/glob + 可选内容匹配）
    3. 第一条匹配的规则决定行为
    4. 无匹配 → 调用 default_behavior_for_mode() 兜底

    用法：
        engine = RuleEngine()
        engine.load_rules(workspace_dir)
        result = engine.evaluate("execute_shell", {"command": "ls"}, mode="default")
    """

    def __init__(self):
        self._rules: list[PermissionRule] = []

    def load_rules(self, workspace_dir: str = "") -> None:
        """从配置加载规则。

        规则来源：
        1. ~/.langcode/config.json → permissions.rules
        2. .langcode/config.json → permissions.rules
        """
        import json
        from pathlib import Path

        self._rules.clear()

        # 用户级规则
        user_path = Path.home() / ".langcode" / "config.json"
        self._load_from_file(user_path, source="user")

        # 项目级规则
        if workspace_dir:
            project_path = Path(workspace_dir) / ".langcode" / "config.json"
            self._load_from_file(project_path, source="project")

        log.info("已加载 %d 条权限规则", len(self._rules))

    def _load_from_file(self, path, source: str) -> None:
        """从配置文件加载规则。"""
        import json

        if not path.exists():
            return
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            rules = cfg.get("permissions", {}).get("rules", [])
            for r in rules:
                self._rules.append(PermissionRule(
                    source=source,
                    tool_pattern=r.get("tool", "*"),
                    behavior=r.get("behavior", "ask"),
                    rule_content=r.get("pattern", ""),
                ))
        except Exception as e:
            log.warning("加载 %s 规则失败: %s", source, e)

    def add_rule(self, rule: PermissionRule) -> None:
        """手动添加规则。"""
        self._rules.append(rule)

    def evaluate(
        self,
        tool_name: str,
        tool_args: dict,
        mode: str = "default",
    ) -> PermissionResult:
        """评估工具调用的权限。

        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            mode: 当前权限模式

        Returns:
            PermissionResult (allow/deny/ask)
        """
        # 按优先级排序后逐条匹配
        sorted_rules = sorted(
            self._rules,
            key=lambda r: _SOURCE_PRIORITY.get(r.source, 99),
        )

        for rule in sorted_rules:
            if self._matches(rule, tool_name, tool_args):
                log.debug("匹配规则: %s/%s → %s", rule.source, rule.tool_pattern, rule.behavior)
                return PermissionResult(
                    behavior=rule.behavior,
                    reason=f"匹配 {rule.source} 规则: {rule.tool_pattern}",
                    requires_user_confirmation=(rule.behavior == "ask"),
                )

        # 无匹配 → 兜底
        return default_behavior_for_mode(mode, tool_name)

    def _matches(self, rule: PermissionRule, tool_name: str, args: dict) -> bool:
        """检查规则是否匹配。

        匹配逻辑（参考 Claude Code toolMatchesRule）：
        1. rule_content 为空 → 只匹配工具名
        2. rule_content 非空 → 匹配工具名 + 内容
        """
        # 工具名匹配（支持 glob）
        if not fnmatch.fnmatch(tool_name, rule.tool_pattern):
            return False

        # 内容匹配
        if rule.rule_content:
            # 对 execute_shell，匹配 command 参数
            command = args.get("command", "")
            if not fnmatch.fnmatch(command, rule.rule_content):
                return False

        return True

    def get_rules_for_display(self) -> list[dict]:
        """返回规则列表（用于 /mode 命令显示）。"""
        return [
            {"source": r.source, "tool": r.tool_pattern,
             "pattern": r.rule_content, "behavior": r.behavior}
            for r in self._rules
        ]
