"""agents/graph_builder — 构建 Supervisor 主图 + 子图。

v2 主图（6 节点 + 子图）：

    START → agent → tools → auto_verify → router → 4-way:
      plan_created → mark_step → agent
      delegated → delegate_router → sub_explore/sub_review → END
      reflect → reflector → agent/END
      react → agent
      __end__ → END

与 v1 的关键差异：
  1. auto_verify 节点：所有代码修改自动验证（代替 CodeAgent 子图）
  2. 去掉 ModeAwareToolNode：改为 _call_llm 中动态工具绑定
  3. 四路分发：plan_created / delegated / reflect / react（代替八路）
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from LangCode.shared.types import LCState
from LangCode.shared.logger import get_logger
from LangCode.agents.router import (
    should_use_tools, process_tool_results, after_tools_routing,
)
from LangCode.agents.verify import auto_verify, after_verify_routing
from LangCode.planning.schema import Plan
from LangCode.planning.context import inject_plan_context

log = get_logger("agents.graph_builder")


def build_supervisor_graph(
    llm: ChatOpenAI,
    tools: list[BaseTool],
    checkpointer: Optional[Checkpointer] = None,
    sub_agent_graphs: Optional[dict[str, CompiledStateGraph]] = None,
) -> CompiledStateGraph:
    """构建 Supervisor 主图。

    Args:
        llm: 主 LLM
        tools: 全量工具列表（含 AST、记忆、plan_create 等）
        checkpointer: LangGraph checkpoint（SqliteSaver）
        sub_agent_graphs: 子图 {"explore": graph, "review": graph}

    Returns:
        编译后的 StateGraph
    """
    builder = StateGraph(LCState)

    # ── 节点定义 ──
    builder.add_node("agent", _make_call_llm(llm, tools))
    builder.add_node("tools", ToolNode(tools=tools))
    builder.add_node("auto_verify", auto_verify)
    builder.add_node("router", process_tool_results)
    builder.add_node("mark_step", _mark_step_in_progress)
    builder.add_node("reflector", _make_reflect(llm))

    # ── 主图边 ──
    builder.add_edge(START, "agent")

    builder.add_conditional_edges("agent", should_use_tools, {
        "tools": "tools",
        "__end__": END,
    })

    builder.add_edge("tools", "auto_verify")

    builder.add_conditional_edges("auto_verify", after_verify_routing, {
        "agent": "agent",
        "router": "router",
    })

    builder.add_conditional_edges("router", after_tools_routing, {
        "plan_created": "mark_step",
        "delegated": "delegate_router",
        "reflect": "reflector",
        "react": "agent",
        "__end__": END,
    })

    builder.add_edge("mark_step", "agent")

    builder.add_conditional_edges("reflector", _after_reflect_routing, {
        "agent": "agent",
        "__end__": END,
    })

    # ── 子图路径 ──
    sub_agent_graphs = sub_agent_graphs or {}
    if sub_agent_graphs:
        builder.add_node("delegate_router", _delegate_router)
        for name, sub_graph in sub_agent_graphs.items():
            builder.add_node(f"sub_{name}", sub_graph)
            builder.add_edge("delegate_router", f"sub_{name}")
            builder.add_edge(f"sub_{name}", END)

    return builder.compile(checkpointer=checkpointer)


def build_explore_subgraph(llm: ChatOpenAI, tools: list[BaseTool],
                           checkpointer=None) -> CompiledStateGraph:
    """构建 Explore Agent 子图。

    子图结构:
    START → agent → tools → agent → ... → summarize → summarize_llm → END

    关键：summarize 节点强制生成结构化摘要，
    中间搜索细节留在子图上下文，只有摘要进入父图 messages。
    """
    explore_tools = [t for t in tools if t.name in (
        "read_file", "search_files", "grep_content", "fetch_api", "execute_shell",
        "memory_search", "memory_list",
    )]

    builder = StateGraph(LCState)
    builder.add_node("agent", _make_call_llm(llm, explore_tools))
    builder.add_node("tools", ToolNode(tools=explore_tools))
    builder.add_node("summarize", _explore_summarize_node)
    builder.add_node("summarize_llm", _make_call_llm(llm, []))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_use_tools, {
        "tools": "tools",
        "summarize": "summarize",
    })
    builder.add_edge("tools", "agent")
    builder.add_edge("summarize", "summarize_llm")
    builder.add_edge("summarize_llm", END)

    return builder.compile(checkpointer=checkpointer)


def build_review_subgraph(llm: ChatOpenAI, tools: list[BaseTool],
                          checkpointer=None) -> CompiledStateGraph:
    """构建 Review Agent 子图。

    子图结构:
    START → agent → tools → agent → ... → report → END

    关键：report 节点使用 raw LLM（不绑定工具）生成审查报告，
    防止 LLM 在报告阶段幻觉 tool_calls。
    """
    review_tools = [t for t in tools if t.name in (
        "read_file", "search_files", "grep_content", "execute_shell", "run_python",
        "memory_search", "memory_list",
    )]

    builder = StateGraph(LCState)
    builder.add_node("agent", _make_call_llm(llm, review_tools))
    builder.add_node("tools", ToolNode(tools=review_tools))
    builder.add_node("report", _make_report(llm))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _review_agent_routing, {
        "tools": "tools",
        "report": "report",
    })
    builder.add_edge("tools", "agent")
    builder.add_edge("report", END)

    return builder.compile(checkpointer=checkpointer)


# ============================================================
#  节点函数工厂
# ============================================================

def _make_call_llm(llm: ChatOpenAI, tools: list[BaseTool]):
    """创建 agent 节点函数。

    动态工具绑定：每次调用时根据 agent_mode 绑定工具子集。
    LLM 只看到它有权限使用的工具 → 从源头避免越权调用。
    """
    def call_llm(state: LCState) -> dict:
        messages = list(state["messages"])

        # 注入计划上下文
        plan_msgs = inject_plan_context(state.get("current_plan"))

        # 注入记忆上下文
        memory = state.get("memory_context", "")
        if memory:
            plan_msgs.insert(0, SystemMessage(id="memory", content=f"[相关记忆]\n{memory}"))

        # 消息组装：System 区域之后插入
        insert_idx = 0
        for i, m in enumerate(messages):
            if isinstance(m, SystemMessage):
                insert_idx = i + 1
        for msg in reversed(plan_msgs):
            messages.insert(insert_idx, msg)

        # 动态工具绑定（如果 tools 列表非空）
        bound_llm = llm
        if tools:
            bound_llm = llm.bind_tools(tools)

        response = bound_llm.invoke(messages)
        return {"messages": [response], "memory_context": ""}

    return call_llm


def _mark_step_in_progress(state: LCState) -> dict:
    """标记当前计划步骤为 in_progress"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return {}
    try:
        plan = Plan(**plan_data)
        current = plan.current()
        if current and current.status == "pending":
            current.status = "in_progress"
        return {"current_plan": plan.model_dump()}
    except Exception:
        return {}


def _make_reflect(llm: ChatOpenAI):
    """创建 reflector 节点函数。

    使用 LLM structured output 评估步骤执行结果。
    """
    from LangCode.planning.reflector import reflect_node

    def reflect(state: LCState) -> dict:
        return reflect_node(state, llm)

    return reflect


def _after_reflect_routing(state: LCState) -> str:
    """reflector 后路由：还有步骤 → agent，完成 → END"""
    plan_data = state.get("current_plan")
    if not plan_data:
        return END
    try:
        plan = Plan(**plan_data)
        if plan.status in ("completed", "abandoned"):
            return END
        return "agent"
    except Exception:
        return END


def _delegate_router(state: LCState) -> dict:
    """构建子Agent 输入消息 — 只有任务描述，不含完整历史"""
    task = state.get("task_description", "")
    if task:
        return {"messages": [HumanMessage(content=task)]}
    return {}


# ============================================================
#  Explore 子图节点
# ============================================================

def _explore_summarize_node(state: LCState) -> dict:
    """注入摘要指令"""
    msg = SystemMessage(content=(
        "[报告生成阶段] 信息收集完毕。\n\n"
        "请基于以上搜索结果生成结构化研究报告：\n"
        "## 研究目标\n[目标描述]\n\n"
        "## 关键发现\n1. [发现1]（含文件路径引用）\n\n"
        "## 代码结构\n[模块/文件 → 作用]\n\n"
        "## 建议\n[可操作建议]\n\n"
        "不要再调用工具。"
    ))
    return {"messages": [msg]}


# ============================================================
#  Review 子图节点
# ============================================================

def _review_agent_routing(state: LCState) -> str:
    """Review Agent 路由：有 tool_calls → tools，否则 → report（但需至少一轮工具调用）"""
    last = state["messages"][-1] if state.get("messages") else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"

    # 检查是否已进行过至少一轮工具调用
    tool_count = sum(
        1 for m in state.get("messages", [])
        if hasattr(m, "tool_calls") and m.tool_calls
    )
    if tool_count >= 1:
        return "report"

    # 还没有工具调用 → 继续调用工具
    return "tools"


def _make_report(llm: ChatOpenAI):
    """创建 report 节点函数（不绑定工具的 raw LLM）"""
    def report_node(state: LCState) -> dict:
        messages = list(state["messages"])
        messages.append(SystemMessage(content=(
            "[报告阶段] 审查信息收集完毕。\n\n"
            "请生成结构化审查报告。包含：\n"
            "1. 总体评价\n"
            "2. 严重程度统计（高/中/低）\n"
            "3. 每个问题的位置 + 建议\n"
            "4. 值得肯定的地方\n\n"
            "不要再调用工具。\n\n"
            "=== 反思检查 ===\n"
            "- 你倾向说'看起来正确'吗？确认你实际验证了每个发现。\n"
            "- 有不确定的地方吗？标注为'建议'而非'必须修复'。"
        )))
        response = llm.invoke(messages)
        return {"messages": [response]}
    return report_node
