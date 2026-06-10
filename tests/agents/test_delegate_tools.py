"""agents/delegate_tools.py — 委托工具测试"""

from unittest.mock import MagicMock

from LangCode.agents.delegate_tools import create_delegate_tools, _make_delegate_tool


class TestCreateDelegateTools:
    def test_returns_three_tools(self):
        tools = create_delegate_tools({})
        assert len(tools) == 3

    def test_tool_names(self):
        tools = create_delegate_tools({})
        names = {t.name for t in tools}
        assert names == {"delegate_to_code", "delegate_to_research", "delegate_to_review"}


class TestDelegateToolBehavior:
    def test_agent_not_registered(self):
        tool_fn = _make_delegate_tool("code", "代码工程师", agents={})
        result = tool_fn.invoke({"task": "写个函数"})
        assert result["success"] is False
        assert "未注册" in result["error"]

    def test_agent_executes_successfully(self):
        mock_agent = MagicMock()
        mock_agent.get_system_prompt.return_value = "你是代码工程师"
        mock_graph = MagicMock()
        mock_agent.get_graph.return_value = mock_graph

        mock_graph.update_state = MagicMock()
        mock_graph.stream.return_value = iter([
            ("updates", {"agent": {"messages": [MagicMock(content="已完成代码编写")]}})
        ])

        tool_fn = _make_delegate_tool("code", "代码工程师", agents={"code": mock_agent})
        result = tool_fn.invoke({"task": "写一个 hello world"})
        assert result["success"] is True
        assert result["agent"] == "code"
        assert "已完成代码编写" in result["summary"]

    def test_agent_execution_exception(self):
        mock_agent = MagicMock()
        mock_agent.get_system_prompt.return_value = "你是代码工程师"
        mock_graph = MagicMock()
        mock_agent.get_graph.return_value = mock_graph
        mock_graph.update_state = MagicMock()
        mock_graph.stream.side_effect = RuntimeError("执行失败")

        tool_fn = _make_delegate_tool("code", "代码工程师", agents={"code": mock_agent})
        result = tool_fn.invoke({"task": "写代码"})
        assert result["success"] is False
        assert "执行失败" in result["error"]
