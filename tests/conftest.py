"""共享测试 fixtures"""

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


@pytest.fixture
def mock_llm():
    """模拟 LLM"""
    return MagicMock()


@pytest.fixture
def ai_tool_message():
    """带工具调用的 AI 消息"""
    return AIMessage(content="", tool_calls=[{"name": "test_tool", "args": {"x": 1}, "id": "tc1"}])


@pytest.fixture
def ai_plain_message():
    """纯文本 AI 消息（无工具调用）"""
    return AIMessage(content="直接回复用户")
