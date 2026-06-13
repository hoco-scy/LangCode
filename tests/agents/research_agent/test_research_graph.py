"""agents/research_agent/graph.py — 纯函数测试"""

from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from LangCode.agents.research_agent.graph import _synthesize_node, ResearchAgent


class TestSynthesizeNode:
    def test_returns_system_message(self):
        state = {"messages": [HumanMessage(content="hi")]}
        result = _synthesize_node(state)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], SystemMessage)
        assert "报告" in result["messages"][0].content


class TestResearchAgentRouting:
    def _make_agent(self):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        return ResearchAgent(llm=mock_llm, checkpoint=None, tools=[])

    def test_tool_calls_returns_tools(self):
        agent = self._make_agent()
        msg = AIMessage(content="", tool_calls=[{"name": "search_files", "args": {}, "id": "tc1"}])
        state = {"messages": [msg]}
        assert agent._agent_routing(state) == "tools"

    def test_no_tool_calls_returns_synthesize(self):
        agent = self._make_agent()
        msg = AIMessage(content="搜索完毕")
        state = {"messages": [msg]}
        assert agent._agent_routing(state) == "synthesize"

    def test_get_system_prompt(self):
        agent = self._make_agent()
        prompt = agent.get_system_prompt()
        assert "研究" in prompt
        assert len(prompt) > 100
