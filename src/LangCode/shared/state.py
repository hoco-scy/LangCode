from typing import Literal, Annotated, Optional, TypedDict
from operator import add
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


class LCState(TypedDict):
    # === 对话 ===
    messages: Annotated[list[AnyMessage], add_messages]

    # === 用户信息 ===
    user_name: str
    platform: Literal["windows", "linux", "mac"]

    # === 工具 ===
    tool_retry_count: int

    # === Agent 路由 ===
    current_agent: Literal["supervisor", "code", "research", "review"]

    # === 模式 ===
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
    delegated_to: Optional[str]            # 委托给哪个子 agent
    sub_agent_results: Annotated[list[dict], add]  # 子 agent 返回结果