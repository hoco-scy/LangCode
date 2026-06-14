"""AppState — 全局应用状态，独立于 LangGraph 图流程。

与 LCState 的关系：
  LCState: 图流程状态（messages, route, current_plan...）
           由 LangGraph SqliteSaver checkpoint 持久化
  AppState: 应用配置状态（用户、会话、权限、统计...）
            由 Store 管理，可选择性持久化到 config.json

图节点通过 get_app_state() 读取 AppState，而不是从 LCState 读取 agent_mode 等字段。
这解耦了图流程和应用配置。

域划分（参考 Claude Code AppStateStore.ts）：
  user:      用户信息（名称、平台、home目录）
  session:   会话配置（agent_mode, model, max_turns, auto_verify...）
  analytics:  遥测统计（工具调用次数、API耗时、Token用量...）
"""

from __future__ import annotations

from typing import Literal, Optional, Callable, Any
from dataclasses import dataclass, field

from LangCode.state.store import create_store, _StoreOps
from LangCode.shared.logger import get_logger

log = get_logger("state.app_state")


@dataclass(frozen=True)
class UserInfo:
    """用户信息"""
    name: str = ""
    platform: Literal["windows", "linux", "mac"] = "linux"
    home_dir: str = ""


@dataclass(frozen=True)
class SessionConfig:
    """会话配置

    agent_mode: 当前权限模式（参考 Claude Code PermissionMode）
    auto_verify: 代码修改后自动验证（LangCode 差异化功能）
    """
    agent_mode: str = "default"       # "plan" | "accept_edits" | "default" | "dont_ask" | "bypass"
    main_loop_model: str = ""
    fast_mode: bool = False
    max_turns: int = 50
    token_budget: Optional[int] = None
    workspace_dir: str = ""
    auto_verify: bool = True          # auto_verify 节点总开关


@dataclass(frozen=True)
class AnalyticsSnapshot:
    """遥测快照 — 参考 Claude Code bootstrap/state.ts 的统计字段。

    用于数据驱动的优化决策，记录关键路径的量化指标。
    """
    session_started_at: str = ""
    total_tool_calls: int = 0
    total_api_calls: int = 0
    total_api_duration_ms: int = 0
    total_tool_duration_ms: int = 0
    total_tokens_used: int = 0
    code_generation_count: int = 0


@dataclass(frozen=True)
class AppState:
    """全局应用状态统一视图。

    使用 frozen=True 保证不可变性——更新时通过 dataclasses.replace() 创建新实例，
    与 Store 的函数式更新器模式（set_state(lambda prev: ...)）配合。
    """
    user: UserInfo = field(default_factory=UserInfo)
    session: SessionConfig = field(default_factory=SessionConfig)
    analytics: AnalyticsSnapshot = field(default_factory=AnalyticsSnapshot)


# ── 全局 Store 单例 ──
# 在 main.py 中通过 init_app_state() 初始化
# 图节点通过 get_app_state() 读取

_app_state_store: Optional[_StoreOps[AppState]] = None


def init_app_state(
    platform: str = "linux",
    workspace_dir: str = "",
    agent_mode: str = "default",
) -> AppState:
    """初始化 AppState Store 单例。

    从 Config 分层加载后调用。main.py 启动时执行一次。

    Args:
        platform: 用户操作系统（windows/linux/mac）
        workspace_dir: 工作区目录
        agent_mode: 初始权限模式

    Returns:
        初始化后的 AppState
    """
    global _app_state_store

    from datetime import datetime, timezone

    initial = AppState(
        user=UserInfo(platform=platform),
        session=SessionConfig(
            agent_mode=agent_mode,
            workspace_dir=workspace_dir,
        ),
        analytics=AnalyticsSnapshot(
            session_started_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    def _on_change(payload: dict) -> None:
        old: AppState = payload["old_state"]
        new: AppState = payload["new_state"]
        if old.session.agent_mode != new.session.agent_mode:
            log.info("agent_mode 变更: %s → %s", old.session.agent_mode, new.session.agent_mode)

    _app_state_store = create_store(initial, on_change=_on_change)
    log.info("AppState 初始化: platform=%s mode=%s workspace=%s",
             platform, agent_mode, workspace_dir)
    return initial


def get_app_state() -> AppState:
    """获取当前 AppState（图节点调用此函数而非从 LCState 读取）。

    Returns:
        当前 AppState 的不可变快照

    Raises:
        RuntimeError: 如果尚未调用 init_app_state()
    """
    if _app_state_store is None:
        raise RuntimeError("AppState 尚未初始化，请先调用 init_app_state()")
    return _app_state_store.get_state()


def update_app_state(updater: Callable[[AppState], AppState]) -> None:
    """更新 AppState（通过函数式更新器）。

    Args:
        updater: (prev: AppState) -> AppState 的更新函数

    Raises:
        RuntimeError: 如果尚未调用 init_app_state()
    """
    if _app_state_store is None:
        raise RuntimeError("AppState 尚未初始化，请先调用 init_app_state()")
    _app_state_store.set_state(updater)


def subscribe_app_state(listener: Callable[[], None]) -> Callable[[], None]:
    """订阅 AppState 变更（返回取消订阅函数）。

    Args:
        listener: 状态变更时的回调

    Returns:
        取消订阅函数
    """
    if _app_state_store is None:
        raise RuntimeError("AppState 尚未初始化，请先调用 init_app_state()")
    return _app_state_store.subscribe(listener)
