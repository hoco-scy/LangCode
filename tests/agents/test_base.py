"""agents/base.py — BaseAgent 基类测试"""

from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from LangCode.agents.base import BaseAgent, MAX_TOOL_RETRIES


class ConcreteAgent(BaseAgent):
    """用于测试的具象 Agent"""
    name = "test"
    description = "测试 Agent"

    def get_system_prompt(self) -> str:
        return "你是测试 Agent"


class TestCallLLM:
    def _make_agent(self, mock_llm=None):
        if mock_llm is None:
            mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        return ConcreteAgent(llm=mock_llm, checkpoint=None, tools=[])

    def test_resets_retry_count(self):
        agent = self._make_agent()
        agent.bound_llm.invoke.return_value = AIMessage(content="ok")
        state = {
            "messages": [HumanMessage(content="hi")],
            "tool_retry_count": 5,
            "memory_context": "",
        }
        result = agent._call_llm(state)
        assert result["tool_retry_count"] == 0

    def test_clears_memory_context(self):
        agent = self._make_agent()
        agent.bound_llm.invoke.return_value = AIMessage(content="ok")
        state = {
            "messages": [HumanMessage(content="hi")],
            "tool_retry_count": 0,
            "memory_context": "一些记忆",
        }
        result = agent._call_llm(state)
        assert result["memory_context"] == ""

    def test_injects_memory_context_as_system_message(self):
        agent = self._make_agent()
        agent.bound_llm.invoke.return_value = AIMessage(content="ok")
        state = {
            "messages": [HumanMessage(content="hi")],
            "tool_retry_count": 0,
            "memory_context": "用户喜欢 Python",
        }
        agent._call_llm(state)
        called_messages = agent.bound_llm.invoke.call_args[0][0]
        memory_msgs = [m for m in called_messages if hasattr(m, 'id') and m.id == "memory_context"]
        assert len(memory_msgs) == 1
        assert "用户喜欢 Python" in memory_msgs[0].content

    def test_retry_limit_appends_warning(self):
        agent = self._make_agent()
        agent.bound_llm.invoke.return_value = AIMessage(content="ok")
        state = {
            "messages": [HumanMessage(content="hi")],
            "tool_retry_count": MAX_TOOL_RETRIES,
            "memory_context": "",
        }
        agent._call_llm(state)
        called_messages = agent.bound_llm.invoke.call_args[0][0]
        tool_messages = [m for m in called_messages if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert "连续失败" in tool_messages[0].content

    def test_returns_ai_message_in_list(self):
        agent = self._make_agent()
        response = AIMessage(content="回答")
        agent.bound_llm.invoke.return_value = response
        state = {
            "messages": [HumanMessage(content="hi")],
            "tool_retry_count": 0,
            "memory_context": "",
        }
        result = agent._call_llm(state)
        assert result["messages"] == [response]


class TestInjectContext:
    def test_default_returns_empty_list(self):
        agent = ConcreteAgent(llm=MagicMock(), checkpoint=None, tools=[])
        result = agent._inject_context({"messages": []})
        assert result == []


class TestGetToolDescriptions:
    def test_returns_formatted_descriptions(self):
        from langchain.tools import tool

        @tool("read_file")
        def read_file(file_path: str) -> str:
            """读取文件内容"""
            return ""

        @tool("write_file")
        def write_file(file_path: str, content: str) -> str:
            """写入文件"""
            return ""

        agent = ConcreteAgent(llm=MagicMock(), checkpoint=None, tools=[read_file, write_file])
        desc = agent.get_tool_descriptions()
        assert "read_file" in desc
        assert "write_file" in desc

    def test_empty_tools(self):
        agent = ConcreteAgent(llm=MagicMock(), checkpoint=None, tools=[])
        desc = agent.get_tool_descriptions()
        assert desc == ""


class TestGetGraph:
    def test_returns_compiled_graph(self):
        agent = ConcreteAgent(llm=MagicMock(), checkpoint=None, tools=[])
        graph = agent.get_graph()
        assert graph is not None
        assert graph is agent.graph
