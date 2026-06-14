"""agents.definition — Agent 定义测试"""

import pytest
from LangCode.agents.definition import AgentDefinition, EXPLORE_AGENT, REVIEW_AGENT


class TestAgentDefinition:
    def test_explore_agent(self):
        assert EXPLORE_AGENT.agent_type == "explore"
        assert EXPLORE_AGENT.omit_claude_md is True
        assert "read_file" in EXPLORE_AGENT.tools
        assert "write_file" in EXPLORE_AGENT.disallowed_tools
        assert "edit_file" in EXPLORE_AGENT.disallowed_tools

    def test_review_agent(self):
        assert REVIEW_AGENT.agent_type == "review"
        assert REVIEW_AGENT.omit_claude_md is False
        assert "read_file" in REVIEW_AGENT.tools
        assert "write_file" in REVIEW_AGENT.disallowed_tools

    def test_custom_agent(self):
        custom = AgentDefinition(
            agent_type="custom",
            description="自定义 Agent",
            tools=["read_file"],
            model="haiku",
        )
        assert custom.agent_type == "custom"
        assert custom.model == "haiku"
        assert custom.omit_claude_md is False

    def test_defaults(self):
        d = AgentDefinition(agent_type="test", description="test agent")
        assert d.model == "inherit"
        assert d.max_turns == 50
        assert d.tools == ["*"]
        assert d.source == "builtin"

    def test_get_system_prompt_empty(self):
        d = AgentDefinition(agent_type="test", description="test")
        assert d.get_system_prompt() == ""

    def test_get_system_prompt_inline(self):
        d = AgentDefinition(
            agent_type="test", description="test",
            system_prompt="你是一个测试 Agent。",
        )
        assert "测试 Agent" in d.get_system_prompt()


class TestAgentToolConstraints:
    def test_explore_forbids_writing(self):
        """Explore Agent 应禁止所有写操作"""
        write_tools = {"write_file", "edit_file", "ast_rename", "ast_add_param"}
        for tool in write_tools:
            assert tool in EXPLORE_AGENT.disallowed_tools

    def test_review_forbids_writing(self):
        """Review Agent 应禁止所有写操作"""
        write_tools = {"write_file", "edit_file", "ast_rename", "ast_add_param"}
        for tool in write_tools:
            assert tool in REVIEW_AGENT.disallowed_tools

    def test_explore_allows_reading(self):
        read_tools = {"read_file", "search_files", "fetch_api"}
        for tool in read_tools:
            assert tool in EXPLORE_AGENT.tools

    def test_review_allows_testing(self):
        """Review Agent 应能运行代码验证"""
        assert "run_python" in REVIEW_AGENT.tools
        assert "execute_shell" in REVIEW_AGENT.tools
