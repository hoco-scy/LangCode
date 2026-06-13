"""路由辅助函数

工具驱动架构下，路由逻辑大幅简化：
- agent 后：有 tool_calls → mode_tools，无 → END
- mode_tools 后：根据工具调用结果路由（plan/delegate/reflect/react）

不再需要正则解析编号列表或 [route: xxx] 标签，
所有路由信号通过 tool calling 传递，确定性高、无歧义。
"""

from langchain_core.messages import AIMessage

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan, PlanStep

log = get_logger("supervisor.router")

MAX_SUPERVISOR_ITERATIONS = 10


def process_tool_results(state: LCState) -> dict:
    """处理工具执行结果：从 tool_calls 中提取 plan 和 delegate 信号，更新状态

    plan_create 工具调用 → 构建 Plan 对象写入 current_plan
    delegate_* 工具调用 → 设置 route 和 task_description
    """
    updates = {}

    messages = state.get("messages", [])
    last_ai = None
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.tool_calls:
            last_ai = m
            break

    if not last_ai:
        return updates

    for tc in last_ai.tool_calls:
        name = tc["name"]
        args = tc.get("args", {})

        if name == "plan_create":
            goal = args.get("goal", "")
            steps_raw = args.get("steps", [])
            steps = [
                PlanStep(step_id=i + 1, description=str(s))
                for i, s in enumerate(steps_raw)
            ]
            plan = Plan(goal=goal or "执行计划", steps=steps)
            updates["current_plan"] = plan.model_dump()
            updates["plan_step_index"] = 0
            updates["agent_mode"] = "build"
            log.info("plan_create 工具调用: %d 步骤", len(steps))

        elif name.startswith("delegate_"):
            agent_name = name.replace("delegate_", "")
            task = args.get("task", "")
            updates["route"] = agent_name
            updates["task_description"] = task
            log.info("delegate 工具调用: agent=%s task=%s", agent_name, task[:50])

    return updates


def after_tools_routing(state: LCState) -> str:
    """mode_tools + process_tool_results 后的路由决策

    优先级：
    1. 刚创建了计划 → mark_step（开始执行第一步）
    2. delegate 工具调用 → delegate_inject
    3. 在计划执行中 → reflector
    4. ReAct 循环继续 → agent
    """
    # 1. 刚创建了计划（所有步骤都是 pending）
    plan_data = state.get("current_plan")
    if plan_data and _is_newly_created_plan(plan_data):
        return "mark_step"

    # 2. delegate
    route = state.get("route", "")
    if route in ("code", "research", "review"):
        return "delegate"

    # 3. 在计划执行中
    if plan_data and _is_step_in_progress(plan_data):
        return "reflector"

    # 4. ReAct 循环
    return "agent"


def _is_newly_created_plan(plan_data: dict) -> bool:
    """判断计划是否刚创建（所有步骤都是 pending，没有 in_progress）"""
    try:
        plan = Plan(**plan_data)
        return (plan.status == "active" and
                len(plan.steps) >= 2 and
                all(s.status == "pending" for s in plan.steps))
    except Exception:
        return False


def _is_step_in_progress(plan_data: dict) -> bool:
    """判断计划是否有步骤正在执行"""
    try:
        plan = Plan(**plan_data)
        return (plan.status == "active" and
                plan.current() is not None and
                plan.current().status == "in_progress")
    except Exception:
        return False
