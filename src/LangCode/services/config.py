"""分层配置系统。

优先级（低→高），参考 Claude Code SettingsSource 层级：
  1. CONFIG_DEFAULTS   — 代码硬编码默认值
  2. user_config       — ~/.langcode/config.json
  3. project_config    — .langcode/config.json
  4. env_vars          — 环境变量覆盖

配置 key 使用点分隔命名（model.name, session.max_turns...）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from LangCode.shared.logger import get_logger

log = get_logger("services.config")

# ── 默认配置 ──
CONFIG_DEFAULTS: dict[str, Any] = {
    "model.name": "mimo-v2.5-pro",
    "model.api_key": "",
    "model.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
    "model.temperature": 0,
    "model.fallback": "",               # fallback 模型名（空则不启用）
    "session.max_turns": 50,
    "session.token_budget": 200_000,       # None 表示不限制
    "permission.mode": "default",
    "verify.auto_enabled": True,
    "verify.run_tests": True,
    "context.max_tokens": 80_000,
    "shell.bash_path": "",              # Windows: git-bash.exe 路径，留空则用 cmd.exe
}

# ── 环境变量映射 ──
# 与 Claude Code 的环境变量覆盖机制等价
_ENV_MAPPING = {
    "LC_MODEL_NAME": "model.name",
    "LC_API_KEY": "model.api_key",
    "LC_BASE_URL": "model.base_url",
    "LC_BASH_PATH": "shell.bash_path",
}


class Config:
    """分层配置管理器。

    用法：
        config = Config.load("/path/to/workspace")
        model_name = config.get("model.name")
        model_cfg = config.get_model()
    """

    def __init__(self, layers: list[dict[str, Any]]):
        self._layers = layers  # 从低到高优先级排列

    @classmethod
    def load(cls, workspace_dir: Optional[str] = None) -> Config:
        """加载所有配置层并合并。

        Args:
            workspace_dir: 项目根目录（用于加载 .langcode/config.json）

        Returns:
            合并后的 Config 实例
        """
        layers: list[dict[str, Any]] = []

        # Layer 1: 默认值
        layers.append(CONFIG_DEFAULTS.copy())

        # Layer 2: 用户配置
        user_path = Path.home() / ".langcode" / "config.json"
        if user_path.exists():
            try:
                user_cfg = json.loads(user_path.read_text(encoding="utf-8"))
                layers.append(_flatten_dict(user_cfg))
                log.debug("加载用户配置: %s", user_path)
            except Exception as e:
                log.warning("加载用户配置失败: %s", e)

        # Layer 3: 项目配置
        if workspace_dir:
            project_path = Path(workspace_dir) / ".langcode" / "config.json"
            if project_path.exists():
                try:
                    project_cfg = json.loads(project_path.read_text(encoding="utf-8"))
                    layers.append(_flatten_dict(project_cfg))
                    log.debug("加载项目配置: %s", project_path)
                except Exception as e:
                    log.warning("加载项目配置失败: %s", e)

        # Layer 4: 环境变量覆盖
        env_overrides: dict[str, Any] = {}
        for env_key, cfg_key in _ENV_MAPPING.items():
            env_val = os.getenv(env_key)
            if env_val:
                env_overrides[cfg_key] = env_val
        if env_overrides:
            layers.append(env_overrides)

        return cls(layers)

    def get(self, key: str, default: Any = None) -> Any:
        """按 key 查询配置值（从高优先级向低查询）。

        Args:
            key: 点分隔配置 key（如 "model.name"）
            default: 未找到时的默认值

        Returns:
            第一个匹配的配置值
        """
        for layer in reversed(self._layers):
            if key in layer:
                return layer[key]
        return default

    def get_model(self) -> dict[str, Any]:
        """获取模型配置（含完整参数）。

        Returns:
            {"name", "api_key", "base_url", "temperature", "fallback"}
        """
        return {
            "name": self.get("model.name", "mimo-v2.5-pro"),
            "api_key": self.get("model.api_key", ""),
            "base_url": self.get("model.base_url", ""),
            "temperature": self.get("model.temperature", 0),
            "fallback": self.get("model.fallback", ""),
        }

    def get_permission_mode(self) -> str:
        """获取初始权限模式。"""
        return self.get("permission.mode", "default")

    def get_max_turns(self) -> int:
        """获取最大轮次限制。"""
        return self.get("session.max_turns", 50)

    def get_token_budget(self) -> Optional[int]:
        """获取 Token 预算限制。None 表示不限制。"""
        return self.get("session.token_budget", None)

    def get_bash_path(self) -> str:
        """获取 bash 路径（Windows: git-bash.exe 路径，其他平台: /bin/bash）。"""
        return self.get("shell.bash_path", "")


def _flatten_dict(d: dict, prefix: str = "") -> dict[str, Any]:
    """将嵌套字典扁平化为点分隔 key。

    例如: {"model": {"name": "xxx"}} → {"model.name": "xxx"}
    """
    result: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_dict(v, full_key))
        else:
            result[full_key] = v
    return result
