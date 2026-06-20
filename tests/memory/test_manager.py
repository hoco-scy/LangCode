"""memory.manager — MemoryManager 测试"""

import json
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.memory.manager import MemoryManager


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "memory.db"
    return SQLiteMemoryStore(db_path=str(db))


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    return llm


@pytest.fixture
def manager(store, mock_llm):
    return MemoryManager(store=store, llm=mock_llm)


class TestGetContext:
    def test_empty_store_returns_empty(self, manager):
        assert manager.get_context("任何查询") == ""

    def test_returns_formatted_memories(self, manager, store):
        store.save(MemoryRecord(content="用户喜欢 Python", memory_type="preference", tags=["python"]))
        store.save(MemoryRecord(content="项目用 LangGraph", memory_type="project", tags=["langgraph"]))
        ctx = manager.get_context("Python")
        assert "用户喜欢 Python" in ctx
        assert "preference" in ctx

    def test_respects_top_k(self, manager, store):
        for i in range(10):
            store.save(MemoryRecord(content=f"记忆{i}", memory_type="fact"))
        ctx = manager.get_context("记忆", top_k=3)
        lines = [l for l in ctx.strip().split("\n") if l.strip()]
        assert len(lines) == 3


class TestSummarizeForInjection:
    def test_truncates_long_context(self, manager, store):
        long_content = "x" * 3000
        store.save(MemoryRecord(content=long_content, memory_type="fact"))
        result = manager.summarize_for_injection("x", max_chars=500)
        assert len(result) <= 600  # 500 + 截断标记
        assert "截断" in result

    def test_short_context_not_truncated(self, manager, store):
        store.save(MemoryRecord(content="短记忆", memory_type="fact"))
        result = manager.summarize_for_injection("短", max_chars=2000)
        assert "短记忆" in result
        assert "截断" not in result


class TestAutoSave:
    def test_skips_without_llm(self, store):
        mgr = MemoryManager(store=store, llm=None)
        messages = [HumanMessage(content="很长的对话" * 50)]
        assert mgr.auto_save(messages) == []

    def test_skips_short_conversation(self, manager):
        messages = [HumanMessage(content="hi")]
        assert manager.auto_save(messages) == []

    def test_saves_valid_json_response(self, manager, store, mock_llm):
        mock_response = MagicMock()
        mock_response.content = json.dumps([{
            "content": "user prefers Python for backend development",
            "memory_type": "preference",
            "tags": ["python"],
        }])
        mock_llm.invoke.return_value = mock_response

        # 消息内容必须足够长（auto_save 要求 conversation >= 50 字符）
        long_msg = (
            "I really enjoy writing Python code and have been using it for over ten years. "
            "I mainly use it for backend development and data processing work."
        )
        messages = [HumanMessage(content=long_msg)]
        saved_ids = manager.auto_save(messages)
        assert len(saved_ids) == 1
        records = store.search("Python", top_k=5)
        assert any("Python" in r.content for r in records)

    def test_handles_markdown_code_block_response(self, manager, store, mock_llm):
        mock_response = MagicMock()
        mock_response.content = '```json\n[{"content": "test memory data", "memory_type": "fact"}]\n```'
        mock_llm.invoke.return_value = mock_response

        long_msg = (
            "This is a long enough conversation message to trigger the auto extraction. "
            "We need it to be over fifty characters total for the feature to activate."
        )
        messages = [HumanMessage(content=long_msg)]
        saved_ids = manager.auto_save(messages)
        assert len(saved_ids) == 1

    def test_handles_invalid_json_gracefully(self, manager, mock_llm):
        mock_response = MagicMock()
        mock_response.content = "this is not valid JSON at all"
        mock_llm.invoke.return_value = mock_response

        long_msg = (
            "This is a long enough conversation message to trigger the auto extraction. "
            "We need it to be over fifty characters total for the feature to activate."
        )
        messages = [HumanMessage(content=long_msg)]
        assert manager.auto_save(messages) == []

    def test_handles_llm_exception_gracefully(self, manager, mock_llm):
        mock_llm.invoke.side_effect = RuntimeError("API error")
        long_msg = (
            "This is a long enough conversation message to trigger the auto extraction. "
            "We need it to be over fifty characters total for the feature to activate."
        )
        messages = [HumanMessage(content=long_msg)]
        assert manager.auto_save(messages) == []
