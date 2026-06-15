"""agents.skills.runner — Skill 执行器。

直接调用 LLM：SystemMessage(skill prompt) + HumanMessage(args)。
需要工具时走简单 tool loop，不需要子图。
"""

from __future__ import annotations

from typing import Any

from LangCode.agents.skills.loader import SkillDefinition
from LangCode.shared.logger import get_logger

log = get_logger("agents.skills.runner")


class SkillRunner:
    """Skill 执行器 — 直接调用 LLM。

    用法：
        runner = SkillRunner(llm, tools)
        result = await runner.run_skill(skill, "审查 src/main.py")
    """

    def __init__(self, llm: Any, tools: list, checkpointer: Any = None):
        self.llm = llm
        self.tools = tools

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

        Returns:
            Skill 执行结果（文本）
        """
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

        log.info("执行 Skill: %s, args: %s", skill.name, args[:100])

        # 构建消息：system prompt + 用户参数
        messages = [SystemMessage(content=skill.prompt)]
        messages.append(HumanMessage(content=args or skill.name))

        # 过滤工具
        skill_tools = []
        if skill.allowed_tools:
            skill_tools = [
                t for t in self.tools
                if getattr(t, "name", "") in skill.allowed_tools
            ]

        # 调用 LLM（有工具时走 tool loop）
        if skill_tools:
            return await self._run_with_tools(messages, skill_tools)

        response = self.llm.invoke(messages)
        return response.content or "[Skill 执行完成，无文本输出]"

    async def _run_with_tools(self, messages: list, tools: list) -> str:
        """带工具的简单 tool loop（最多 5 轮）。"""
        from langchain_core.messages import AIMessage, ToolMessage

        bound = self.llm.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

        for _ in range(5):
            response: AIMessage = bound.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                return response.content or "[Skill 执行完成，无文本输出]"

            for tc in response.tool_calls:
                tool = tool_map.get(tc["name"])
                if tool:
                    result = tool.invoke(tc["args"])
                    messages.append(ToolMessage(
                        content=str(result)[:2000],
                        tool_call_id=tc["id"],
                    ))

        return messages[-1].content if isinstance(messages[-1], AIMessage) else "[Skill 执行超限]"
