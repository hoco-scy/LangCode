from typing import Literal, Annotated, Optional, TypedDict
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


def _last_wins(_old, new):
    """reducer: 多个节点同一步更新同一 key 时，取最后一个值"""
    return new


class LCState(TypedDict):
    # === 对话 ===
    messages: Annotated[list[AnyMessage], add_messages]

    # === 用户信息 ===
    user_name: str
    platform: Literal["windows", "linux", "mac"]

    # === 工具 ===
    tool_retry_count: Annotated[int, _last_wins]

    # === Agent 路由 ===
    current_agent: Literal["supervisor", "code", "research", "review"]

    # === 模式 ===
    agent_mode: Literal["plan", "build"]
    dangerous_edit_mode: bool
    strict_mode: bool

    # === 计数 ===
    content_generation_count: int
    tool_calls_count: int
    code_generation_count: int

    # === 记忆 ===
    memory_context: str                    # 检索到的相关记忆，注入 LLM 上下文

    # === 规划 ===
    current_plan: Optional[dict]           # 当前执行计划（JSON 序列化的 Plan）
    plan_step_index: int                   # 当前执行到第几步

    # === 多Agent ===
    task_description: str                  # 当前任务描述
    verify_errors: Optional[list[str]]     # CodeAgent 验证节点发现的错误列表

    # === Supervisor 路由 ===
    route: Annotated[str, _last_wins]      # supervisor 中枢路由决策
    supervisor_iterations: Annotated[int, _last_wins]  # 回环迭代计数