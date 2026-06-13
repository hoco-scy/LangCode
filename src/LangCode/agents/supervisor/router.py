"""路由决策模型 + 辅助路由函数

Agent 的第一次 LLM 调用同时完成思考和路由决策，通过以下机制：
1. tool_calls（如果 LLM 选择了工具）→ tools 路径
2. plan_steps（如果 LLM 输出了计划步骤）→ plan 路径
3. route 标签 [route: code|research|review task: ...] → delegate 路径
4. 否则 → END

不再需要单独的 supervisor 路由节点，节省一次 LLM 调用。
"""

import re
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan, PlanStep

log = get_logger("supervisor.router")

MAX_SUPERVISOR_ITERATIONS = 10

# route 标签的正则匹配
_ROUTE_TAG_RE = re.compile(
    r'\[route:\s*(code|research|review)\s*(?:task:\s*(.*?))?\]',
    re.IGNORECASE | re.DOTALL,
)


class AgentDecision(BaseModel):
    """Agent 的决策 schema（用于 structured output 的 plan 路径）

    Agent 可以选择直接回复（react）或创建计划（plan），
    通过 plan_steps 字段区分。
    """
    model_config = {"populate_by_name": True}

    content: str = Field(
        default="", description="回复用户的内容"
    )
    reasoning: str = Field(
        default="",
        alias="reason",
        description="决策理由"
    )
    plan_steps: list[str] = Field(
        default_factory=list,
        description="如果任务需要多步执行，这里列出计划步骤。简单任务留空。"
    )


# ============================================================
#  路由决策函数（从 agent 响应中提取，不需要额外 LLM 调用）
# ============================================================

def extract_decision_from_agent(state: LCState) -> dict:
    """从 agent 的响应中提取路由决策，更新 state 中的 route 字段

    决策逻辑（纯确定性，无 LLM 调用）：
    1. 有 tool_calls → route="react"（由 _agent_routing 处理）
    2. 有 plan_steps → route="plan"
    3. 有 [route: code|research|review] 标签 → route=对应值
    4. 否则 → route="end"
    """
    messages = state.get("messages", [])
    if not messages:
        return {"route": "end"}

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage):
        return {"route": "end"}

    # 1. 有 tool_calls → react（tool 执行后再判断）
    if last_msg.tool_calls:
        return {"route": "react"}

    # 2. 检查是否包含 plan_steps（AgentDecision 格式）
    #    通过 additional_kwargs 或特殊标记传递
    plan_steps = _extract_plan_steps(last_msg)
    if plan_steps:
        log.info("路由决策: plan（%d 步骤）", len(plan_steps))
        return {
            "route": "plan",
            "plan_steps": plan_steps,
            "task_description": _extract_task_from_content(last_msg.content),
        }

    # 3. 检查 [route: xxx] 标签
    content = str(last_msg.content or "")
    match = _ROUTE_TAG_RE.search(content)
    if match:
        route = match.group(1).lower()
        task = (match.group(2) or "").strip()
        log.info("路由决策: %s (task=%s)", route, task[:50])
        return {
            "route": route,
            "task_description": task or content[:200],
        }

    # 4. 默认 END
    return {"route": "end"}


def _extract_plan_steps(msg: AIMessage) -> list[str]:
    """从 AIMessage 中提取计划步骤

    检查 additional_kwargs 中的 plan_steps 字段。
    Agent._call_llm 会将 AgentDecision 的 plan_steps 存入 additional_kwargs。
    """
    # 从 additional_kwargs 中读取（由 agent 节点在检测到 plan_steps 时写入）
    plan_steps = getattr(msg, '_plan_steps', None)
    if plan_steps and isinstance(plan_steps, list):
        return [str(s) for s in plan_steps if s]

    # 也检查 additional_kwargs
    ak = msg.additional_kwargs or {}
    plan_steps = ak.get("plan_steps")
    if plan_steps and isinstance(plan_steps, list):
        return [str(s) for s in plan_steps if s]

    return []


def _extract_task_from_content(content) -> str:
    """从 agent 的回复中提取任务描述（取前 200 字符）"""
    if not content:
        return ""
    text = str(content).strip()
    # 去掉 route 标签
    text = _ROUTE_TAG_RE.sub("", text).strip()
    return text[:200]


# ============================================================
#  Plan 创建（从 agent 的分析结果直接构建，无需额外 LLM 调用）
# ============================================================

def plan_create_from_agent(state: LCState) -> dict:
    """从 agent 输出的 plan_steps 创建计划

    不调用 LLM，直接解析 agent 的分析结果构建 Plan 对象。
    """
    plan_steps_str = state.get("plan_steps", [])
    task = state.get("task_description", "")

    if not plan_steps_str:
        log.warning("plan_create_from_agent: 无计划步骤")
        return {}

    steps = [
        PlanStep(step_id=i + 1, description=s)
        for i, s in enumerate(plan_steps_str)
    ]
    plan = Plan(goal=task or "执行计划", steps=steps)

    log.info("从 agent 输出创建计划: %d 步骤", len(steps))
    return {
        "current_plan": plan.model_dump(),
        "plan_step_index": 0,
        "agent_mode": "build",  # 执行阶段用 build 模式
    }


# ============================================================
#  辅助路由函数
# ============================================================

def should_create_plan(state: LCState) -> Literal["plan_create", "__end__"]:
    """agent 后路由：有 plan_steps → plan_create，否则 → END"""
    route = state.get("route", "end")
    if route == "plan" and state.get("plan_steps"):
        return "plan_create"
    return "__end__"


def delegate_routing(state: LCState) -> Literal["code_agent", "research_agent", "review_agent", "__end__"]:
    """agent 后路由：delegate 路径"""
    route = state.get("route", "end")
    if route in ("code", "research", "review"):
        return f"{route}_agent"
    return "__end__"
