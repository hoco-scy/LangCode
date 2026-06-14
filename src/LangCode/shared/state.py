"""LCState — LangGraph 图流程状态定义。

v2 变更说明（保持向后兼容）：
  当前保留所有 v1 字段，Phase 4 重建 Agent 系统时再移除废弃字段。
  标注 [DEPRECATED Phase 4] 的字段将在 Phase 4 迁移到 AppState 或移除。
  标注 [v2 NEW] 的字段是 v2 新增的图流程字段。

v2 最终目标（8 字段）：
  messages, route, current_plan, task_description,
  verify_errors, memory_context, supervisor_iterations
"""

from typing import Literal, Annotated, Optional, TypedDict
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


def _last_wins(_old, new):
    """reducer: 多个节点同一步更新同一 key 时，取最后一个值"""
    return new


class LCState(TypedDict):
    # === 对话核心 ===
    messages: Annotated[list[AnyMessage], add_messages]

    # === 用户信息 [DEPRECATED Phase 4 → AppState.user] ===
    user_name: str
    platform: Literal["windows", "linux", "mac"]

    # === 工具 [DEPRECATED Phase 4 → engine/recovery] ===
    tool_retry_count: Annotated[int, _last_wins]

    # === Agent 路由 [DEPRECATED Phase 4 → 运行时局部变量] ===
    current_agent: Literal["supervisor", "code", "research", "review"]

    # === 模式 [DEPRECATED Phase 4 → AppState.session.agent_mode] ===
    agent_mode: Literal["plan", "build"]
    dangerous_edit_mode: bool
    strict_mode: bool

    # === 计数 [DEPRECATED Phase 4 → AppState.analytics] ===
    content_generation_count: int
    tool_calls_count: int
    code_generation_count: int

    # === 记忆 [v2 KEEP] ===
    memory_context: str                    # 检索到的相关记忆，注入 LLM 上下文

    # === 规划 [v2 KEEP current_plan; plan_step_index DEPRECATED] ===
    current_plan: Optional[dict]           # 当前执行计划（JSON 序列化的 Plan）
    plan_step_index: int                   # [DEPRECATED Phase 4] current_plan.current_step_index() 替代

    # === 多Agent [v2 KEEP] ===
    task_description: str                  # 当前任务描述
    verify_errors: Optional[list[str]]     # 验证节点发现的错误列表

    # === Supervisor 路由 [v2 KEEP route + supervisor_iterations] ===
    route: Annotated[str, _last_wins]      # supervisor 中枢路由决策
    plan_steps: list[str]                  # [DEPRECATED Phase 4] current_plan.steps 替代
    supervisor_iterations: Annotated[int, _last_wins]  # 回环迭代计数
