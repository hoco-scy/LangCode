"""agents.skills.runner — Skill 执行器。

Fork 子Agent 执行 Skill。
"""

from __future__ import annotations

import uuid
from typing import Any

from LangCode.agents.skills.loader import SkillDefinition
from LangCode.shared.logger import get_logger

log = get_logger("agents.skills.runner")


class SkillRunner:
    """Skill 执行器 — Fork 子Agent 执行 Skill。

    用法：
        runner = SkillRunner(llm, tools, checkpointer)
        result = await runner.run_skill(skill, "审查 src/main.py", parent_ctx)
    """

    def __init__(self, llm: Any, tools: list, checkpointer: Any = None):
        self.llm = llm
        self.tools = tools
        self.checkpointer = checkpointer

    async def run_skill(
        self,
        skill: SkillDefinition,
        args: str,
        parent_context: Any = None,
    ) -> str:
        """执行 Skill。

        Args:
            skill: Skill 定义
            args: 用户传入的参数
            parent_context: 父 Agent 上下文

        Returns:
            Skill 执行结果（文本）
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        from langgraph.graph import StateGraph, START, END
        from LangCode.shared.types import LCState

        log.info("执行 Skill: %s, args: %s", skill.name, args[:100])

        # 构建 Skill 提示词
        skill_prompt = skill.prompt
        if args:
            skill_prompt += f"\n\n## 用户参数\n{args}"

        # 过滤工具
        skill_tools = self.tools
        if skill.allowed_tools:
            skill_tools = [
                t for t in self.tools
                if getattr(t, "name", "") in skill.allowed_tools
            ]

        # 构建子图
        def _call_llm(state):
            messages = list(state["messages"])
            messages.insert(0, SystemMessage(content=skill_prompt))
            bound = self.llm.bind_tools(skill_tools)
            response = bound.invoke(messages)
            return {"messages": [response]}

        def _should_use_tools(state):
            from langchain_core.messages import AIMessage
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                return "tools"
            return "__end__"

        from langgraph.prebuilt import ToolNode
        builder = StateGraph(LCState)
        builder.add_node("agent", _call_llm)
        builder.add_node("tools", ToolNode(tools=skill_tools))
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", _should_use_tools, {
            "tools": "tools", "__end__": END,
        })
        builder.add_edge("tools", "agent")

        graph = builder.compile(checkpointer=self.checkpointer)

        # 执行（skill 是一次性执行，每次生成独立 thread_id）
        thread_id = f"skill-{skill.name}-{uuid.uuid4().hex[:8]}"
        result = graph.invoke(
            {"messages": [HumanMessage(content=args or skill.name)]},
            {"configurable": {"thread_id": thread_id}},
        )

        # 提取最后一条 AI 消息
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "ai":
                return msg.content or "[Skill 执行完成，无文本输出]"

        return "[Skill 执行完成]"
