"""agents/delegate_tools.py — Command Handoff 委托工具测试"""

from unittest.mock import MagicMock

from langgraph.types import Command
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from LangCode.agents.delegate_tools import create_delegate_tools, _make_handoff_tool


def _mock_agents():
    """创建包含三个 mock agent 的字典"""
    agents = {}
    for name, desc in [("code", "代码工程师"), ("research", "代码研究员"), ("review", "代码审查员")]:
        agent = MagicMock()
        agent.get_system_prompt.return_value = f"你是{desc}"
        agent.description = desc
        agents[name] = agent
    return agents


class TestCreateDelegateTools:
    def test_returns_three_tools(self):
        tools = create_delegate_tools(_mock_agents())
        assert len(tools) == 3

    def test_tool_names(self):
        tools = create_delegate_tools(_mock_agents())
        names = {t.name for t in tools}
        assert names == {"delegate_to_code", "delegate_to_research", "delegate_to_review"}


class TestHandoffToolBehavior:
    def _make_mock_agent(self, prompt="你是代码工程师", desc="代码工程师"):
        agent = MagicMock()
        agent.get_system_prompt.return_value = prompt
        agent.description = desc
        return agent

    def test_returns_command_with_correct_goto(self):
        agents = {"code": self._make_mock_agent()}
        tool_fn = _make_handoff_tool("code", agents)
        result = tool_fn.invoke({"task": "写一个 hello world", "tool_call_id": "tc1"})
        assert isinstance(result, Command)
        assert result.goto == "code_agent"

    def test_command_update_contains_messages(self):
        agents = {"code": self._make_mock_agent(prompt="你是代码工程师")}
        tool_fn = _make_handoff_tool("code", agents)
        result = tool_fn.invoke({"task": "写一个 hello world", "tool_call_id": "tc1"})
        messages = result.update["messages"]
        assert len(messages) == 3
        assert isinstance(messages[0], ToolMessage)
        assert messages[0].tool_call_id == "tc1"
        assert "code" in messages[0].content
        assert isinstance(messages[1], SystemMessage)
        assert "你是代码工程师" in messages[1].content
        assert isinstance(messages[2], HumanMessage)
        assert messages[2].content == "写一个 hello world"

    def test_context_appended_to_system_prompt(self):
        agents = {"code": self._make_mock_agent(prompt="你是代码工程师")}
        tool_fn = _make_handoff_tool("code", agents)
        result = tool_fn.invoke({"task": "写代码", "context": "项目用 Python 3.11", "tool_call_id": "tc1"})
        sys_content = result.update["messages"][1].content
        assert "你是代码工程师" in sys_content
        assert "项目用 Python 3.11" in sys_content

    def test_research_agent_goto(self):
        agents = {"research": self._make_mock_agent(prompt="你是研究员")}
        tool_fn = _make_handoff_tool("research", agents)
        result = tool_fn.invoke({"task": "分析代码结构", "tool_call_id": "tc2"})
        assert result.goto == "research_agent"

    def test_review_agent_goto(self):
        agents = {"review": self._make_mock_agent(prompt="你是审查员")}
        tool_fn = _make_handoff_tool("review", agents)
        result = tool_fn.invoke({"task": "审查代码质量", "tool_call_id": "tc3"})
        assert result.goto == "review_agent"
