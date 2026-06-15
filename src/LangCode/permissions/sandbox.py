"""permissions.sandbox — 工作目录锁定 + 路径边界校验。

参考 Claude Code pathValidation.ts:
- 所有文件操作必须在 allowed_dirs 范围内
- 解析符号链接后再检查边界
- additional_working_directories 支持多工作区
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("permissions.sandbox")


class PathSandbox:
    """路径沙箱 — 文件操作边界校验。

    所有文件工具（read_file, write_file, edit_file 等）在执行前
    通过此沙箱校验路径是否在允许范围内。

    用法：
        sandbox = PathSandbox("/home/user/project")
        if sandbox.is_path_allowed("/home/user/project/src/main.py"):
            # 允许
        if sandbox.is_path_allowed("/etc/passwd"):
            # 拒绝
    """

    def __init__(
        self,
        workspace_dir: str,
        additional_dirs: Optional[list[str]] = None,
    ):
        self.allowed_dirs: set[str] = set()
        # 主工作区
        main = self._resolve(workspace_dir)
        if main:
            self.allowed_dirs.add(main)
        # 附加工作区
        if additional_dirs:
            for d in additional_dirs:
                resolved = self._resolve(d)
                if resolved:
                    self.allowed_dirs.add(resolved)

    def is_path_allowed(self, path: str) -> bool:
        """检查路径是否在允许的目录树内。

        解析符号链接后检查边界，防止符号链接逃逸。
        """
        if not self.allowed_dirs:
            return True  # 无限制

        resolved = self._resolve(path)
        if not resolved:
            return False

        for allowed in self.allowed_dirs:
            if resolved == allowed or resolved.startswith(allowed + os.sep):
                return True
        return False

    def resolve_safe_path(self, raw_path: str) -> Optional[str]:
        """解析路径，如果越界返回 None。"""
        if self.is_path_allowed(raw_path):
            return str(Path(raw_path).resolve())
        return None

    def validate_file_operation(self, operation: str, path: str) -> tuple[bool, str]:
        """验证文件操作。

        Args:
            operation: 操作类型（"read", "write", "edit", "delete"）
            path: 文件路径

        Returns:
            (is_safe, reason)
        """
        if not path:
            return False, "路径为空"

        resolved = self._resolve(path)
        if not resolved:
            return False, f"路径解析失败: {path}"

        if not self.is_path_allowed(path):
            return False, f"路径越界: {path} 不在允许的工作区内"

        # 额外安全检查
        if operation == "delete":
            # 不允许删除工作区根目录
            if resolved in self.allowed_dirs:
                return False, "不允许删除工作区根目录"

        return True, ""

    def _resolve(self, path: str) -> Optional[str]:
        """解析路径（处理 .. 和符号链接）。"""
        try:
            p = Path(path).resolve()
            return str(p)
        except (OSError, ValueError):
            return None

    def __repr__(self) -> str:
        dirs = ", ".join(sorted(self.allowed_dirs))
        return f"PathSandbox(allowed=[{dirs}])"
