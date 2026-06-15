"""agents/graph_builder — 构建 Supervisor 主图 + 子图。

v3 主图（5 节点 + 子图）：

    START → agent → tools → auto_verify → router → 2-way:
      delegated → dequeue_delegation → delegate_router → sub_explore/sub_review → agent
      react → agent

计划管理通过 write_todo / update_todo / modify_todo 工具完成，
在 tools 节点正常执行，由 router.process_tool_results 更新 state。
上下文注入在 _call_llm 中通过 build_plan_context 完成。
"""

from __future__ import annotations

import time
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
from LangCode.planning.context import build_plan_context

log = get_logger("agents.graph_builder")


def build_supervisor_graph(
    llm: ChatOpenAI,
    tools: list[BaseTool],
    checkpointer: Optional[Checkpointer] = None,
    sub_agent_graphs: Optional[dict[str, CompiledStateGraph]] = None,
    llm_client=None,
) -> CompiledStateGraph:
    """构建 Supervisor 主图。

    Args:
        llm: 主 LLM
        tools: 全量工具列表（含 AST、记忆、todo 工具等）
        checkpointer: LangGraph checkpoint（SqliteSaver）
        sub_agent_graphs: 子图 {"explore": graph, "review": graph}
        llm_client: LLMClient 实例（用于 429 重试后 fallback）

    Returns:
        编译后的 StateGraph
    """
    builder = StateGraph(LCState)

    # ── 节点定义 ──
    builder.add_node("agent", _make_call_llm(llm, tools, llm_client))
    builder.add_node("tools", ToolNode(tools=tools))
    builder.add_node("auto_verify", auto_verify)
    builder.add_node("router", process_tool_results)
    builder.add_node("dequeue_delegation", _dequeue_delegation)

    # ── 主图边 ──
    builder.add_edge(START, "agent")

    builder.add_conditional_edges("agent", should_use_tools, {
        "tools": "tools",
        "router": "router",
        "__end__": END,
    })

    builder.add_edge("tools", "auto_verify")

    builder.add_conditional_edges("auto_verify", after_verify_routing, {
        "agent": "agent",
        "router": "router",
    })

    builder.add_conditional_edges("router", after_tools_routing, {
        "delegated": "dequeue_delegation",
        "react": "agent",
    })

    # ── 子图路径 ──
    sub_agent_graphs = sub_agent_graphs or {}
    if sub_agent_graphs:
        sub_route_map = {f"sub_{name}": f"sub_{name}" for name in sub_agent_graphs}
        sub_route_map["__end__"] = END

        builder.add_node("delegate_router", _delegate_router)
        builder.add_edge("dequeue_delegation", "delegate_router")
        builder.add_conditional_edges("delegate_router", _select_sub_agent, sub_route_map)
        for name, sub_graph in sub_agent_graphs.items():
            builder.add_node(f"sub_{name}", sub_graph)
            # 子图完成后回到 agent，由 LLM 继续执行（如需委派更多任务）
            builder.add_edge(f"sub_{name}", "agent")

    return builder.compile(checkpointer=checkpointer)


def build_explore_subgraph(llm: ChatOpenAI, tools: list[BaseTool],
                           checkpointer=None, llm_client=None) -> CompiledStateGraph:
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
    builder.add_node("agent", _make_call_llm(llm, explore_tools, llm_client))
    builder.add_node("tools", ToolNode(tools=explore_tools))
    builder.add_node("summarize", _explore_summarize_node)
    builder.add_node("summarize_llm", _make_call_llm(llm, [], llm_client))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _explore_routing, {
        "tools": "tools",
        "summarize": "summarize",
    })
    builder.add_edge("tools", "agent")
    builder.add_edge("summarize", "summarize_llm")
    builder.add_edge("summarize_llm", END)

    return builder.compile(checkpointer=checkpointer)


def build_review_subgraph(llm: ChatOpenAI, tools: list[BaseTool],
                          checkpointer=None, llm_client=None) -> CompiledStateGraph:
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
    builder.add_node("agent", _make_call_llm(llm, review_tools, llm_client))
    builder.add_node("tools", ToolNode(tools=review_tools))
    builder.add_node("report", _make_report(llm, llm_client))

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

def _make_call_llm(llm: ChatOpenAI, tools: list[BaseTool], llm_client=None):
    """创建 agent 节点函数。

    动态工具绑定：每次调用时根据 agent_mode 绑定工具子集。
    LLM 只看到它有权限使用的工具 → 从源头避免越权调用。

    429 重试：指数退避重试，最终尝试 fallback 模型。
    """
    def call_llm(state: LCState) -> dict:
        messages = list(state["messages"])

        # 注入计划上下文（紧跟系统提示词之后）
        plan_text = build_plan_context(state.get("current_plan"))
        if plan_text:
            insert_idx = 0
            for i, m in enumerate(messages):
                if isinstance(m, SystemMessage):
                    insert_idx = i + 1
            messages.insert(insert_idx, SystemMessage(id="plan_context", content=plan_text))

        # 注入记忆上下文（在计划上下文之后）
        memory = state.get("memory_context", "")
        if memory:
            # 找到 plan_context 插入后的位置
            mem_idx = insert_idx + (1 if plan_text else 0)
            messages.insert(mem_idx, SystemMessage(id="memory", content=f"[相关记忆]\n{memory}"))

        # 动态工具绑定（如果 tools 列表非空）
        bound_llm = llm
        if tools:
            bound_llm = llm.bind_tools(tools)

        response = _invoke_with_retry(bound_llm, messages, llm_client, llm, tools)
        return {"messages": [response], "memory_context": ""}

    return call_llm


def _invoke_with_retry(bound_llm, messages, llm_client, raw_llm, tools,
                       max_retries: int = 3, base_delay: float = 2.0):
    """带指数退避的 LLM 调用，429 限速时自动重试，最终尝试 fallback。

    Args:
        bound_llm: 已绑定工具的 LLM 实例
        messages: 消息列表
        llm_client: LLMClient 实例（用于 fallback），可为 None
        raw_llm: 原始 LLM 实例（用于 fallback 时重新绑定工具）
        tools: 工具列表（用于 fallback 时重新绑定）
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数（指数退避）
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return bound_llm.invoke(messages)
        except Exception as e:
            last_error = e
            error_str = str(e)

            # 只对 429/529/503 等可重试错误进行重试
            is_retryable = any(code in error_str for code in ("429", "529", "503", "rate", "Rate"))

            if not is_retryable or attempt >= max_retries:
                # 不可重试或已用完重试次数 → 尝试 fallback
                if llm_client and llm_client.switch_to_fallback():
                    log.warning("主模型失败 (%s)，切换到 fallback 模型重试", error_str[:80])
                    fallback_bound = llm_client.primary_model
                    if tools:
                        fallback_bound = fallback_bound.bind_tools(tools)
                    try:
                        return fallback_bound.invoke(messages)
                    except Exception as fallback_err:
                        log.error("fallback 模型也失败: %s", fallback_err)
                        raise fallback_err from e
                raise

            delay = base_delay * (2 ** attempt)
            log.warning("LLM 调用失败 (attempt %d/%d): %s — %.1fs 后重试",
                        attempt + 1, max_retries, error_str[:80], delay)
            time.sleep(delay)

    raise last_error


def _delegate_router(state: LCState) -> dict:
    """构建子Agent 输入消息 — 只有任务描述，不含完整历史"""
    task = state.get("task_description", "")
    if task:
        return {"messages": [HumanMessage(content=task)]}
    return {}


def _dequeue_delegation(state: LCState) -> dict:
    """从委派队列取出下一个任务，设置 route + task_description"""
    pending = list(state.get("_pending_delegations", []))
    if not pending:
        log.debug("dequeue_delegation: 队列为空")
        return {}
    next_item = pending.pop(0)
    log.info("委派出队: agent=%s, 剩余=%d", next_item.get("route", ""), len(pending))
    return {
        "route": next_item.get("route", ""),
        "task_description": next_item.get("task", ""),
        "_pending_delegations": pending,
    }


def _select_sub_agent(state: LCState) -> str:
    """根据 route 选择对应的子图节点名"""
    route = state.get("route", "")
    if route == "explore":
        return "sub_explore"
    if route == "review":
        return "sub_review"
    return "__end__"


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


def _explore_routing(state: LCState) -> str:
    """Explore Agent 路由：有 tool_calls → tools，否则 → summarize（强制生成摘要）"""
    last = state["messages"][-1] if state.get("messages") else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "summarize"


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


def _make_report(llm: ChatOpenAI, llm_client=None):
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
        response = _invoke_with_retry(llm, messages, llm_client, llm, [])
        return {"messages": [response]}
    return report_node
