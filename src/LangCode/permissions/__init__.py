"""permissions — 权限系统。

- model: PermissionMode 五层模式 + PermissionResult 三元决策
- rules: RuleEngine 三层优先级规则匹配
- classifier: BashClassifier 命令语义分析
- sandbox: PathSandbox 路径边界校验
"""

from LangCode.permissions.model import PermissionResult, PermissionMode, default_behavior_for_mode
from LangCode.permissions.rules import RuleEngine, PermissionRule
from LangCode.permissions.classifier import BashClassifier
from LangCode.permissions.sandbox import PathSandbox

__all__ = [
    "PermissionResult", "PermissionMode", "default_behavior_for_mode",
    "RuleEngine", "PermissionRule",
    "BashClassifier",
    "PathSandbox",
]
