"""agents — 多 Agent 协作系统"""

from LangCode.agents.base import BaseAgent
from LangCode.agents.delegate_tools import create_delegate_tools

__all__ = [
    "BaseAgent",
    "create_delegate_tools",
]
