"""ToolUseContext — 工具执行环境的依赖注入载体。

参考 Claude Code ToolUseContext 设计：
- 每个查询轮次创建一个 Context
- 通过参数显式传递（非隐式全局变量）
- 子Agent 创建时继承父 Context 并覆盖 agent_id + 重置文件缓存
- 轮次结束销毁

关键设计（参考 Claude Code）：
- read_file_cache: LRU 文件读缓存 → 避免重复磁盘 I/O
- write_file_state: 本轮已写入文件集合 → 用于 auto_verify 提取修改文件
- can_use_tool: 权限检查回调 → 工具自行调用
- abort_signal: 取消令牌 → 子任务可被父任务取消
- allowed_dirs: 路径白名单 → PathSandbox 使用
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from pathlib import Path


@dataclass
class ToolUseContext:
    """工具执行上下文。

    生命周期：单次查询轮次。
    创建：QueryEngine 或 Supervisor 在每轮开始时创建。
    传递：传给每个工具的 call() 和 check_permissions() 方法。
    销毁：轮次结束后由 Python GC 回收。

    clone_for_subagent() 创建子Agent 专用副本：
    - 独立的文件缓存（子Agent 读取不影响父）
    - 独立的写入追踪（子Agent 的修改独立于父）
    - 独立的 agent_id（标识是哪个 Agent 在执行）
    - 共享 permission_mode 和 allowed_dirs（继承父的安全约束）
    """

    # ── 会话标识 ──
    session_id: str
    agent_id: str                      # 当前 Agent 标识（"supervisor", "explore", "review"）
    workspace_dir: str                 # 工作目录

    # ── LLM 配置 ──
    model_name: str
    max_output_tokens: int = 8192

    # ── 工具环境 ──
    tools: list = field(default_factory=list)          # 所有可用工具
    can_use_tool: Optional[Callable] = None            # CanUseToolFn: 权限检查回调

    # ── 文件缓存 ──
    # read_file_cache: 文件路径 → (内容, mtime) — LRU 策略
    # 避免重复读取同一文件，同时检测文件变更
    read_file_cache: dict = field(default_factory=dict)

    # write_file_state: 本轮已写入/修改的文件路径集合
    # 用于 auto_verify 提取需要验证的文件
    write_file_state: set = field(default_factory=set)

    # ── 权限 ──
    permission_mode: str = "default"   # PermissionMode
    allowed_dirs: set = field(default_factory=set)   # PathSandbox 路径白名单

    # ── MCP ──
    mcp_clients: list = field(default_factory=list)

    # ── 中断控制 ──
    # 使用 asyncio.Event 作为取消令牌
    # 父任务通过 set() 通知子任务取消
    abort_signal: Optional[Any] = None

    # ── 遥测 ──
    telemetry: dict = field(default_factory=dict)

    def clone_for_subagent(self, agent_id: str) -> ToolUseContext:
        """为子Agent 创建独立的上下文副本。

        子Agent 获得：
        - 独立的文件缓存（子Agent 读取不影响父缓存）
        - 独立的写入追踪（子Agent 的修改独立追踪）
        - 共享的权限约束（permission_mode, allowed_dirs）
        - 共享的 abort_signal（父取消时子也取消）

        Args:
            agent_id: 子Agent 的标识（如 "explore", "review"）

        Returns:
            新的 ToolUseContext 实例
        """
        return ToolUseContext(
            session_id=self.session_id,
            agent_id=agent_id,
            workspace_dir=self.workspace_dir,
            model_name=self.model_name,
            max_output_tokens=self.max_output_tokens,
            tools=list(self.tools),
            can_use_tool=self.can_use_tool,
            read_file_cache={},                    # 独立文件缓存
            write_file_state=set(),                # 独立写入追踪
            permission_mode=self.permission_mode,
            allowed_dirs=set(self.allowed_dirs),
            mcp_clients=list(self.mcp_clients),
            abort_signal=self.abort_signal,        # 共享取消令牌
            telemetry={},
        )

    def record_write(self, file_path: str) -> None:
        """记录文件写入（用于 auto_verify 提取修改文件）。"""
        self.write_file_state.add(str(Path(file_path).resolve()))

    def clear_file_cache(self, file_path: Optional[str] = None) -> None:
        """清除文件缓存。

        Args:
            file_path: 指定文件路径则只清除该文件；None 则清除全部
        """
        if file_path:
            self.read_file_cache.pop(file_path, None)
        else:
            self.read_file_cache.clear()
