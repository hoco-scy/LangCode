"""supervisor — 主控 Agent

ReAct + Plan-and-Execute 双模式编排器。
简单任务走 ReAct 循环，复杂任务走 Plan → Execute → Reflect 流程。
"""

from LangCode.agents.supervisor.graph import SupervisorAgent
from LangCode.agents.supervisor.prompts import AGENT_PROMPT

__all__ = [
    "SupervisorAgent",
    "AGENT_PROMPT",
]
