"""中枢路由节点 — Supervisor 的核心决策层

使用 LLM structured output 决定下一步路由，不依赖 tool_call。
路由选项：react（普通ReAct循环）、plan（Plan-and-Execute）、
code/research/review（委派给子Agent）、end（结束）。

回环模式：每条子路径完成后回到 supervisor，由 supervisor 决定下一步。
最大迭代保护：超过 MAX_SUPERVISOR_ITERATIONS 强制结束。
"""

from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.planning.schema import Plan

log = get_logger("supervisor.router")

MAX_SUPERVISOR_ITERATIONS = 10


class SupervisorDecision(BaseModel):
    """Supervisor 路由决策的 structured output schema"""
    model_config = {"populate_by_name": True}

    route: Literal["react", "plan", "code", "research", "review"] = Field(
        description="下一步路由：react=普通对话+工具, plan=规划复杂任务, code/research/review=委派给子Agent"
    )
    reasoning: str = Field(
        default="",
        alias="reason",
        description="路由决策的理由"
    )
    task: str = Field(
        default="", description="委派给子Agent的任务描述（仅 code/research/review 路由时需要）"
    )
    mode: Literal["plan", "build"] = Field(
        default="build", description="建议的权限模式：plan=只读不可编辑, build=全权限"
    )


SUPERVISOR_ROUTER_PROMPT = """你是 LangCode 的中枢路由决策者。你的任务是分析当前对话状态，决定下一步应该走哪条路径。

## 可用路径

1. **react** — 普通对话 + 工具调用循环
   - 适用于：简单问题、单步任务、直接回答
   - 工具可用性取决于当前权限模式

2. **plan** — Plan-and-Execute 模式
   - 适用于：多步骤复杂任务、需要先规划再执行的任务
   - 流程：先只读分析制定计划 → 用户确认 → 逐步执行
   - 3步以上的任务应优先选择 plan

3. **code** — 委派给 Code Agent
   - 适用于：明确的代码编写/修改/调试任务
   - Code Agent 有验证节点，修改后自动检查语法和测试

4. **research** — 委派给 Research Agent
   - 适用于：代码搜索、结构分析、信息收集、生成研究报告

5. **review** — 委派给 Review Agent
   - 适用于：代码审查、安全分析、质量评估

## 权限模式

- **plan 模式**：只读，可用工具：read_file, search_files, fetch_api, memory_search, memory_list
- **build 模式**：全权限，包括 write_file, edit_file, execute_shell, run_python, ast_* 工具

## 决策规则

- 简单问答/单步操作 → react
- 3步以上复杂任务 → plan（如果当前没有活跃计划）
- 专门的代码编写 → code
- 专门的搜索分析 → research
- 专门的代码审查 → review
- 如果已有活跃计划在执行中 → react（继续执行当前步骤）
- 任务已完成，无需更多操作 → react（直接回复用户）

请输出 JSON 格式的路由决策。
"""


def supervisor_node(state: LCState, llm: ChatOpenAI) -> dict:
    """中枢路由节点：调用 LLM structured output 决定下一步路由"""
    iterations = state.get("supervisor_iterations", 0)

    # 迭代保护
    if iterations >= MAX_SUPERVISOR_ITERATIONS:
        log.warning("supervisor 迭代上限 (%d)，强制结束", MAX_SUPERVISOR_ITERATIONS)
        return {
            "route": "end",
            "supervisor_iterations": iterations + 1,
        }

    # 构建路由提示上下文
    context_parts = []

    # 计划状态
    plan_data = state.get("current_plan")
    if plan_data and isinstance(plan_data, dict):
        try:
            plan = Plan(**plan_data)
            context_parts.append(f"当前计划状态: {plan.status}, 步骤 {plan.current_step + 1}/{len(plan.steps)}")
        except Exception:
            context_parts.append("当前计划数据存在但解析失败")

    # 权限模式
    mode = state.get("agent_mode", "build")
    context_parts.append(f"当前权限模式: {mode}")

    # 任务描述
    task_desc = state.get("task_description", "")
    if task_desc:
        context_parts.append(f"当前任务: {task_desc[:100]}")

    # 最近消息摘要
    messages = state.get("messages", [])
    if messages:
        last_human = ""
        for m in reversed(messages):
            if hasattr(m, "type") and m.type == "human" and m.content:
                last_human = str(m.content)[:200]
                break
        if last_human:
            context_parts.append(f"最近用户消息: {last_human}")

    context_str = "\n".join(context_parts)

    # 调用 LLM structured output
    decision_llm = llm.with_structured_output(SupervisorDecision)

    prompt_messages = [
        SystemMessage(content=SUPERVISOR_ROUTER_PROMPT),
        SystemMessage(content=f"## 当前状态\n{context_str}"),
    ]

    # 添加最近几条消息作为参考
    recent_msgs = messages[-6:] if messages else []
    for m in recent_msgs:
        prompt_messages.append(m)

    try:
        decision = decision_llm.invoke(prompt_messages)
        log.info("supervisor 路由: %s (mode=%s) — %s", decision.route, decision.mode, decision.reasoning[:100])

        updates = {
            "route": decision.route,
            "agent_mode": decision.mode,
            "supervisor_iterations": iterations + 1,
        }

        # 委派时设置任务描述
        if decision.route in ("code", "research", "review") and decision.task:
            updates["task_description"] = decision.task

        return updates

    except Exception as e:
        log.warning("supervisor 路由决策失败（fallback react）: %s", e)
        return {
            "route": "react",
            "agent_mode": mode,
            "supervisor_iterations": iterations + 1,
        }


def supervisor_routing(state: LCState) -> str:
    """条件边函数：根据 state["route"] 返回路由目标

    返回值是路由键名（react/plan/code/research/review/end），
    由 graph.py 的动态路由映射转换为实际节点名。
    """
    route = state.get("route", "react")

    # 迭代保护
    iterations = state.get("supervisor_iterations", 0)
    if iterations > MAX_SUPERVISOR_ITERATIONS:
        log.warning("supervisor_routing: 超过迭代上限，强制 end")
        return "end"

    valid_routes = {"react", "plan", "code", "research", "review", "end"}
    if route not in valid_routes:
        log.warning("supervisor_routing: 无效路由 '%s', 默认 react", route)
        return "react"

    return route
