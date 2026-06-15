"""LCState — LangGraph 图流程状态定义。

v2 最终版（8 字段）：
  仅包含图表流转所需的字段。
  用户偏好、模式配置、统计 → AppState (Store)
  每个字段有明确的"设置者"和"消费者"
"""

from typing import Literal, Annotated, Optional, TypedDict
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


def _last_wins(_old, new):
    """Reducer: 多节点同时更新同一 key 时取最后值"""
    return new


class LCState(TypedDict):
    """LangGraph 图流程状态 — 仅包含图表流转所需的字段

    设计原则：
    - 只放图流程相关字段（路由信号、跨节点通信、图执行上下文）
    - 用户偏好、模式配置、统计 → AppState (Store)
    - 每个字段有明确的"设置者"和"消费者"
    """

    # ── 对话核心 ──
    # 设置者: agent + tools + 用户入口  消费者: 所有 LLM 调用
    messages: Annotated[list[AnyMessage], add_messages]

    # ── 路由信号（瞬态：设置后立即消费，不跨轮次）──
    # 设置者: router.process_tool_results
    # 消费者: router.after_tools_routing
    route: Annotated[str, _last_wins]

    # ── 计划上下文（生命周期: plan_create → plan_complete/abandon）──
    # 设置者: router.process_tool_results
    # 消费者: supervisor._call_llm (注入) + reflector (评估) + _after_reflect (路由)
    current_plan: Optional[dict]

    # ── 子Agent 通信 ──
    # 设置者: router.process_tool_results（delegate_* 工具调用时）
    # 消费者: supervisor._delegate_router（构建子Agent 输入消息）
    task_description: str

    # ── 验证闭环 ──
    # 设置者: supervisor._auto_verify（工具执行后、router 之前）
    # 消费者: supervisor._after_verify（路由回 agent 或继续）
    verify_errors: Annotated[Optional[list[str]], _last_wins]

    # ── 记忆上下文 ──
    # 设置者: cli（每轮对话前从 MemoryManager 检索）
    # 消费者: supervisor._call_llm（注入到 LLM 消息）
    memory_context: str

    # ── 迭代控制 ──
    # 设置者: after_tools_routing（回环时 +1）
    # 消费者: router（防止死循环，> MAX_ITERATIONS → END）
    supervisor_iterations: Annotated[int, _last_wins]
