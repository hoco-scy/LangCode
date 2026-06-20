"""agents.graph_builder — 核心节点函数单元测试"""

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from LangCode.agents.graph_builder import (
    _dequeue_delegation,
    _select_sub_agent,
    _explore_summarize_node,
    _explore_routing,
    _delegate_router,
    build_supervisor_graph,
    build_explore_subgraph,
    build_review_subgraph,
)


# ── _dequeue_delegation ──

class TestDequeueDelegation:
    def test_dequeues_first_item(self):
        state = {
            "_pending_delegations": [
                {"route": "explore", "task": "搜索"},
                {"route": "review", "task": "审查"},
            ],
        }
        result = _dequeue_delegation(state)
        assert result["route"] == "explore"
        assert result["task_description"] == "搜索"
        assert len(result["_pending_delegations"]) == 1

    def test_empty_queue_returns_empty(self):
        result = _dequeue_delegation({"_pending_delegations": []})
        assert result == {}

    def test_missing_key_returns_empty(self):
        result = _dequeue_delegation({})
        assert result == {}


# ── _select_sub_agent ──

class TestSelectSubAgent:
    def test_explore(self):
        assert _select_sub_agent({"route": "explore"}) == "sub_explore"

    def test_review(self):
        assert _select_sub_agent({"route": "review"}) == "sub_review"

    def test_unknown_route(self):
        assert _select_sub_agent({"route": "unknown"}) == "__end__"

    def test_empty_route(self):
        assert _select_sub_agent({"route": ""}) == "__end__"

    def test_missing_route(self):
        assert _select_sub_agent({}) == "__end__"


# ── _delegate_router ──

class TestDelegateRouter:
    def test_creates_human_message_from_task(self):
        state = {"task_description": "搜索所有 Python 文件"}
        result = _delegate_router(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], HumanMessage)
        assert "搜索" in result["messages"][0].content

    def test_empty_task_returns_empty(self):
        assert _delegate_router({"task_description": ""}) == {}

    def test_missing_task_returns_empty(self):
        assert _delegate_router({}) == {}


# ── _explore_summarize_node ──

class TestExploreSummarizeNode:
    def test_returns_system_message(self):
        result = _explore_summarize_node({"messages": []})
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], SystemMessage)
        assert "报告生成" in msgs[0].content
        assert "不要再调用工具" in msgs[0].content


# ── _explore_routing ──

class TestExploreRouting:
    def test_with_tool_calls_goes_to_tools(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read", "args": {}}]),
        ]}
        assert _explore_routing(state) == "tools"

    def test_without_tool_calls_goes_to_summarize(self):
        state = {"messages": [AIMessage(content="搜索完成")]}
        assert _explore_routing(state) == "summarize"

    def test_empty_messages_goes_to_summarize(self):
        assert _explore_routing({"messages": []}) == "summarize"


# ── 图编译验证 ──

class TestGraphCompilation:
    @pytest.fixture
    def llm(self):
        m = MagicMock()
        m.bind_tools.return_value = m
        m.invoke.return_value = AIMessage(content="ok")
        return m

    def test_main_graph_has_expected_nodes(self, llm):
        graph = build_supervisor_graph(llm, [])
        nodes = set(graph.nodes.keys())
        assert "agent" in nodes
        assert "tools" in nodes
        assert "auto_verify" in nodes
        assert "router" in nodes
        assert "dequeue_delegation" in nodes

    def test_main_graph_with_subgraphs(self, llm):
        explore = build_explore_subgraph(llm, [])
        graph = build_supervisor_graph(llm, [], sub_agent_graphs={"explore": explore})
        nodes = set(graph.nodes.keys())
        assert "sub_explore" in nodes
        assert "delegate_router" in nodes

    def test_explore_subgraph_nodes(self, llm):
        graph = build_explore_subgraph(llm, [])
        nodes = set(graph.nodes.keys())
        assert "agent" in nodes
        assert "tools" in nodes
        assert "summarize" in nodes
        assert "summarize_llm" in nodes

    def test_review_subgraph_nodes(self, llm):
        graph = build_review_subgraph(llm, [])
        nodes = set(graph.nodes.keys())
        assert "agent" in nodes
        assert "tools" in nodes
        assert "report" in nodes

    def test_explore_filters_tools(self, llm):
        """Explore 子图只保留只读工具"""
        from langchain.tools import tool as lc_tool

        @lc_tool
        def read_file(file_path: str) -> str:
            """读取文件"""
            return ""

        @lc_tool
        def write_file(file_path: str, content: str) -> str:
            """写入文件"""
            return ""

        @lc_tool
        def search_files(pattern: str) -> str:
            """搜索文件"""
            return ""

        graph = build_explore_subgraph(llm, [read_file, write_file, search_files])
        assert graph is not None
        nodes = set(graph.nodes.keys())
        assert "summarize" in nodes

    def test_review_filters_tools(self, llm):
        from langchain.tools import tool as lc_tool

        @lc_tool
        def read_file(file_path: str) -> str:
            """读取文件"""
            return ""

        @lc_tool
        def write_file(file_path: str, content: str) -> str:
            """写入文件"""
            return ""

        @lc_tool
        def execute_shell(command: str) -> str:
            """执行命令"""
            return ""

        graph = build_review_subgraph(llm, [read_file, write_file, execute_shell])
        assert graph is not None
        nodes = set(graph.nodes.keys())
        assert "report" in nodes
