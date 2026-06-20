"""agents/router — 路由决策：工具调用信号提取 + 分发。

v3 简化：
- plan_create 拦截 → write_todo / update_todo / modify_todo 拦截
- 移除 plan_created / reflect 路由分支（不再需要反思器）
- 计划执行完全由 LLM 自行管理，系统只提供上下文注入引导
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage

from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan, PlanStep

log = get_logger("agents.router")


def should_use_tools(state: dict) -> str:
    """agent 节点后：有 tool_calls → "tools"，有待处理委派 → "router"，否则 → "__end__"

    当 LLM 不再调用工具但有待处理的委派队列时，必须走 router 出队执行。
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    # 无 tool_calls 但有待处理委派队列 → 走 router 出队
    if state.get("_pending_delegations"):
        return "router"
    return "__end__"


def process_tool_results(state: dict) -> dict:
    """从上一轮 LLM 的 tool_calls 中提取 todo/delegate 信号。

    write_todo / update_todo / modify_todo 和 delegate_* 工具的"真正执行者"。
    工具函数本身只返回成功 JSON，真正的 Plan 操作在此处完成。
    原因：LangChain tool 无法直接修改 LangGraph 状态。

    防重复消费：仅处理最近一轮中未标记过的 todo/delegate_* 调用。

    Returns:
        状态更新 dict（current_plan / route / task_description）
    """
    updates: dict = {}
    messages = state.get("messages", [])

    last_ai = _find_last_ai_with_tool_calls(messages)
    if not last_ai:
        return updates

    # 已处理过的 tool_call id，防止跨多轮重复消费
    _ids_str = state.get("_processed_tool_ids", "")
    processed = set(_ids_str.split(",")) if _ids_str else set()

    for tc in last_ai.tool_calls:
        name = tc.get("name", "")
        tc_id = tc.get("id", "")
        args = tc.get("args", {})

        if tc_id in processed:
            continue

        if name == "write_todo":
            processed.add(tc_id)
            _handle_write_todo(args, updates, state)
            log.info("write_todo: goal=%s, %d 步",
                     args.get("goal", "")[:50], len(args.get("steps", [])))

        elif name == "update_todo":
            processed.add(tc_id)
            _handle_update_todo(args, updates, state)
            log.info("update_todo: step=%s status=%s",
                     args.get("step_index"), args.get("status"))

        elif name == "modify_todo":
            processed.add(tc_id)
            _handle_modify_todo(args, updates, state)
            log.info("modify_todo: called")

        elif name.startswith("delegate_"):
            processed.add(tc_id)
            agent_name = name.replace("delegate_", "")
            task = args.get("task", "")
            pending = list(updates.get("_pending_delegations",
                                       state.get("_pending_delegations", [])))
            pending.append({"route": agent_name, "task": task})
            updates["_pending_delegations"] = pending
            log.info("delegate 工具调用入队: agent=%s, task=%s", agent_name, task[:50])

    if processed:
        updates["_processed_tool_ids"] = ",".join(processed)

    log.debug("process_tool_results: processed=%d pending_delegations=%s",
              len(processed), len(updates.get("_pending_delegations", [])))
    return updates


def after_tools_routing(state: dict) -> str:
    """tools + router 后：分发。

    优先级：
    1. 委派队列有待处理 → "delegated"
    2. 其他 → "react"（ReAct 循环继续）
    """
    pending = state.get("_pending_delegations", [])

    if pending:
        return "delegated"

    return "react"


# ── Todo 工具处理 ──

def _handle_write_todo(args: dict, updates: dict, state: dict):
    """处理 write_todo 调用：创建新 Plan"""
    goal = args.get("goal", "")
    steps_raw = args.get("steps", [])
    steps = [
        PlanStep(step_id=i + 1, description=str(s))
        for i, s in enumerate(steps_raw)
    ]
    # 第一步自动标记为 in_progress
    if steps:
        steps[0].status = "in_progress"
    plan = Plan(goal=goal or "执行计划", steps=steps)
    updates["current_plan"] = plan.model_dump()


def _handle_update_todo(args: dict, updates: dict, state: dict):
    """处理 update_todo 调用：更新步骤状态或整个计划状态"""
    plan_data = updates.get("current_plan") or state.get("current_plan")
    if not plan_data:
        log.warning("update_todo: 无活跃计划")
        return

    try:
        plan = Plan(**plan_data)
    except Exception:
        return

    step_index = args.get("step_index", 0)
    status = args.get("status", "")
    result = args.get("result", "")

    # step_index=0 → 更新整个计划
    if step_index == 0:
        if status == "completed":
            plan.mark_completed()
        elif status == "abandoned":
            plan.mark_abandoned()
        updates["current_plan"] = plan.model_dump()
        return

    # step_index > 0 → 更新指定步骤
    target = None
    for s in plan.steps:
        if s.step_id == step_index:
            target = s
            break

    if not target:
        log.warning("update_todo: 步骤 %d 不存在", step_index)
        return

    if status == "done":
        target.status = "done"
        target.result = result or "已完成"
        # 自动推进到下一个 pending 步骤
        if plan.current_step == step_index - 1:
            plan.current_step += 1
            next_step = plan.current()
            if next_step and next_step.status == "pending":
                next_step.status = "in_progress"
            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
    elif status == "failed":
        target.status = "failed"
        target.error = result or "执行失败"
    elif status == "skipped":
        target.status = "skipped"
        if plan.current_step == step_index - 1:
            plan.current_step += 1
            next_step = plan.current()
            if next_step and next_step.status == "pending":
                next_step.status = "in_progress"
            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
    elif status == "in_progress":
        target.status = "in_progress"

    updates["current_plan"] = plan.model_dump()


def _handle_modify_todo(args: dict, updates: dict, state: dict):
    """处理 modify_todo 调用：增删替换步骤"""
    plan_data = updates.get("current_plan") or state.get("current_plan")
    if not plan_data:
        log.warning("modify_todo: 无活跃计划")
        return

    try:
        plan = Plan(**plan_data)
    except Exception:
        return

    steps_replace = args.get("steps")
    add_steps = args.get("add_steps")
    remove_indices = args.get("remove_indices")

    # 完全替换
    if steps_replace is not None:
        plan.steps = [
            PlanStep(step_id=i + 1, description=str(s))
            for i, s in enumerate(steps_replace)
        ]
        plan.current_step = 0
        if plan.steps:
            plan.steps[0].status = "in_progress"

    # 追加
    if add_steps:
        next_id = len(plan.steps) + 1
        for i, desc in enumerate(add_steps):
            plan.steps.append(PlanStep(step_id=next_id + i, description=str(desc)))

    # 删除（从高到低索引避免偏移）
    if remove_indices:
        remove_set = set(remove_indices)
        plan.steps = [s for s in plan.steps if s.step_id not in remove_set]
        # 重新编号
        for i, s in enumerate(plan.steps):
            s.step_id = i + 1
        # 确保 current_step 不越界
        if plan.current_step >= len(plan.steps):
            plan.current_step = max(0, len(plan.steps) - 1)

    updates["current_plan"] = plan.model_dump()


# ── 辅助函数 ──

def _find_last_ai_with_tool_calls(messages: list[BaseMessage]) -> Optional[AIMessage]:
    """从消息列表中找到最近一个含 tool_calls 的 AIMessage。"""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.tool_calls:
            return m
    return None
