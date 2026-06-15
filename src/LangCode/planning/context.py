"""Plan context injection — 将计划上下文注入 LLM 消息。

在 Supervisor._call_llm() 的消息组装阶段调用。
注入位置：紧跟系统提示词之后、记忆上下文之前。

注入内容：
1. 当前计划的 TODO 列表（含状态图标）
2. 执行规则（对齐确认、及时更新、异常处理等）
"""

from __future__ import annotations

from typing import Optional

from LangCode.planning.schema import Plan
from LangCode.shared.logger import get_logger

log = get_logger("planning.context")

STATUS_ICONS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "done": "[x]",
    "failed": "[!]",
    "skipped": "[-]",
}


def build_plan_context(plan_data: Optional[dict]) -> Optional[str]:
    """构建计划上下文文本。

    Args:
        plan_data: LCState.current_plan (dict 形式的 Plan)

    Returns:
        注入文本（str），无计划或计划已结束时返回 None
    """
    if not plan_data:
        return None

    try:
        plan = Plan(**plan_data)
    except Exception:
        return None

    if plan.status in ("completed", "abandoned"):
        return None

    # ── TODO 列表 ──
    lines = [
        f"═══ 执行计划 ═══",
        f"",
        f"目标：{plan.goal}",
        f"",
    ]

    # 进度统计
    done_count = sum(1 for s in plan.steps if s.status == "done")
    lines.append(f"进度：{done_count}/{len(plan.steps)}")

    for step in plan.steps:
        icon = STATUS_ICONS.get(step.status, "[?]")
        marker = " ← 当前" if step.step_id - 1 == plan.current_step else ""
        lines.append(f"  {icon} {step.step_id}. {step.description}{marker}")
        if step.result:
            lines.append(f"     → {step.result[:120]}")
        if step.error:
            lines.append(f"     ✗ {step.error[:120]}")

    # ── 执行规则 ──
    current = plan.current()
    current_desc = current.description if current else "无"

    lines.extend([
        f"",
        f"═══ 执行规则 ═══",
        f"",
        f"1. 你当前正在执行计划，请确保你的每一个操作都服务于当前步骤目标",
        f"2. 当前聚焦步骤「{current_desc}」，不要提前做后续步骤的工作",
        f"3. 每完成一个步骤，立即调用 update_todo 标记为 done 并附上简要结果",
        f"4. 如果某步骤失败，调用 update_todo 标记为 failed 并说明原因",
        f"5. 如果发现计划需要调整（增删步骤），调用 modify_todo 修改",
        f"6. 所有步骤完成后，调用 update_todo(step_index=0, status=completed) 标记计划完成",
        f"7. 如果当前步骤遇到阻碍无法继续，向用户说明情况而非停滞",
    ])

    return "\n".join(lines)
