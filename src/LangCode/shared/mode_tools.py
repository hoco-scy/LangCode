"""权限模式工具节点 — 按 agent_mode 过滤可用工具

plan 模式：只读工具（read_file, search_files, fetch_api, memory_*）
build 模式：全部工具（含 write_file, edit_file, execute_shell, run_python, ast_*）

ModeAwareToolNode 在执行时根据 state["agent_mode"] 动态过滤工具，
对越权工具调用返回权限拒绝消息。
"""

from typing import Sequence

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger

log = get_logger("shared.mode_tools")

# plan 模式允许的工具名集合
PLAN_MODE_TOOLS = frozenset({
    "read_file",
    "search_files",
    "fetch_api",
    "memory_search",
    "memory_list",
    "plan_show",
    "plan_create",        # 创建计划（执行时自动切换到 build 模式）
    "delegate_code",      # 委派给子Agent
    "delegate_research",
    "delegate_review",
})


def filter_tools_for_mode(tools: Sequence[BaseTool], mode: str) -> list[BaseTool]:
    """根据权限模式过滤工具列表

    Args:
        tools: 全量工具列表
        mode: "plan" 或 "build"

    Returns:
        过滤后的工具列表
    """
    if mode == "build":
        return list(tools)

    return [t for t in tools if t.name in PLAN_MODE_TOOLS]


class ModeAwareToolNode(ToolNode):
    """按权限模式过滤工具的 ToolNode

    执行时从 state 读取 agent_mode，过滤掉越权工具。
    如果 LLM 尝试调用越权工具，返回权限拒绝消息而非执行。
    """

    def __init__(self, tools: Sequence[BaseTool], **kwargs):
        self._all_tools = list(tools)
        # 传给父类的是全量工具（因为 LLM 可能看到全部工具 schema）
        # 实际执行时按 mode 过滤
        super().__init__(tools=tools, **kwargs)

    def _filter_tool_calls(self, state: LCState, tool_calls: list[dict]) -> tuple[list[dict], list[dict]]:
        """将 tool_calls 分为允许和越权两组"""
        mode = state.get("agent_mode", "build")
        if mode == "build":
            return tool_calls, []

        allowed = []
        denied = []
        for tc in tool_calls:
            if tc["name"] in PLAN_MODE_TOOLS:
                allowed.append(tc)
            else:
                denied.append(tc)
                log.warning("plan 模式下拒绝工具调用: %s", tc["name"])

        return allowed, denied

    def invoke(self, state: LCState, config=None, **kwargs):
        """执行工具调用，按 mode 过滤越权调用"""
        # 提取 LLM 的 tool_calls
        messages = state.get("messages", [])
        from langchain_core.messages import AIMessage
        last_ai = None
        for m in reversed(messages):
            if isinstance(m, AIMessage) and m.tool_calls:
                last_ai = m
                break

        if not last_ai:
            return super().invoke(state, config, **kwargs)

        mode = state.get("agent_mode", "build")
        if mode == "build":
            return super().invoke(state, config, **kwargs)

        # plan 模式：过滤 tool_calls
        allowed_calls, denied_calls = self._filter_tool_calls(state, last_ai.tool_calls)

        if not denied_calls:
            return super().invoke(state, config, **kwargs)

        # 为越权调用生成拒绝消息
        denied_messages = []
        for tc in denied_calls:
            denied_messages.append(ToolMessage(
                content=f"[权限拒绝] 当前处于 plan（只读）模式，不允许使用 {tc['name']} 工具。"
                        f"可用工具: {', '.join(PLAN_MODE_TOOLS)}。"
                        f"如需执行写操作，请切换到 build 模式（/mode build）。",
                tool_call_id=tc["id"],
            ))

        # 只执行允许的调用
        if allowed_calls:
            # 临时修改 last_ai 的 tool_calls 为仅允许的
            original_calls = last_ai.tool_calls
            last_ai.tool_calls = allowed_calls
            result = super().invoke(state, config, **kwargs)
            last_ai.tool_calls = original_calls

            # 追加拒绝消息
            if hasattr(result, 'messages') and result.get('messages'):
                result["messages"] = result["messages"] + denied_messages
            else:
                result = {"messages": denied_messages}
            return result
        else:
            # 全部被拒绝
            return {"messages": denied_messages}
