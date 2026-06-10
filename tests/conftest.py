"""共享测试 fixtures"""

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


@pytest.fixture
def memory_store():
    """内存 SQLite 记忆存储"""
    from LangCode.memory.store import SQLiteMemoryStore
    return SQLiteMemoryStore(db_path=":memory:")


@pytest.fixture
def session_store():
    """内存 SQLite 会话索引存储"""
    from LangCode.shared.session import SessionStore
    return SessionStore(db_path=":memory:")


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


@pytest.fixture
def sample_plan():
    """示例计划（3 步骤）"""
    from LangCode.planning.schema import Plan, PlanStep
    return Plan(
        goal="测试目标",
        steps=[
            PlanStep(step_id=1, description="步骤一"),
            PlanStep(step_id=2, description="步骤二"),
            PlanStep(step_id=3, description="步骤三"),
        ]
    )
