"""agents/review_agent/graph.py — 纯函数测试"""

from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from LangCode.agents.review_agent.graph import _report_node, ReviewAgent, MIN_REVIEW_ROUNDS


class TestReportNode:
    def test_calls_raw_llm_with_report_prompt(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="审查报告")
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="分析完毕")]}
        result = _report_node(state, mock_llm)
        assert "messages" in result
        called_messages = mock_llm.invoke.call_args[0][0]
        assert any("报告" in m.content for m in called_messages if isinstance(m, SystemMessage))
        assert result["messages"][0].content == "审查报告"


class TestReviewAgentRouting:
    def _make_agent(self):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        return ReviewAgent(llm=mock_llm, checkpoint=None, tools=[])

    def test_tool_calls_returns_tools(self):
        agent = self._make_agent()
        msg = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "tc1"}])
        state = {"messages": [msg]}
        assert agent._agent_routing(state) == "tools"

    def test_no_tool_calls_with_prior_rounds_returns_report(self):
        agent = self._make_agent()
        state = {"messages": [
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "tc1"}]),
            SystemMessage(content="结果"),
            AIMessage(content="审查完毕"),
        ]}
        assert agent._agent_routing(state) == "report"

    def test_no_tool_calls_no_prior_rounds_returns_tools(self):
        agent = self._make_agent()
        state = {"messages": [
            AIMessage(content="还没有做过工具调用"),
        ]}
        assert agent._agent_routing(state) == "tools"

    def test_get_system_prompt(self):
        agent = self._make_agent()
        prompt = agent.get_system_prompt()
        assert "审查" in prompt
        assert len(prompt) > 100
