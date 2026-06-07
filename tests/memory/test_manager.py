"""memory/manager.py — MemoryManager 测试（mock LLM）"""

import json
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.memory.manager import MemoryManager


class TestGetContext:
    def test_returns_empty_when_no_memories(self, memory_store):
        manager = MemoryManager(store=memory_store)
        assert manager.get_context("anything") == ""

    def test_returns_formatted_context(self, memory_store):
        memory_store.save(MemoryRecord(content="用户喜欢 Python", memory_type="preference", tags=["lang"]))
        manager = MemoryManager(store=memory_store)
        ctx = manager.get_context("Python")
        assert "用户喜欢 Python" in ctx
        assert "preference" in ctx
        assert "lang" in ctx

    def test_respects_top_k(self, memory_store):
        for i in range(10):
            memory_store.save(MemoryRecord(content=f"Python 记忆 {i}", memory_type="fact"))
        manager = MemoryManager(store=memory_store)
        ctx = manager.get_context("Python", top_k=3)
        # 应该只有 3 条
        lines = [l for l in ctx.split("\n") if l.strip()]
        assert len(lines) == 3


class TestAutoSave:
    def test_skips_short_conversation(self, memory_store):
        llm = MagicMock()
        manager = MemoryManager(store=memory_store, llm=llm)
        messages = [HumanMessage(content="hi")]
        result = manager.auto_save(messages)
        assert result == []
        llm.invoke.assert_not_called()

    def test_saves_when_llm_returns_items(self, memory_store):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = json.dumps([
            {"content": "用户喜欢 Vim", "memory_type": "preference", "tags": ["editor"]}
        ])
        llm.invoke.return_value = resp
        manager = MemoryManager(store=memory_store, llm=llm)

        messages = [
            HumanMessage(content="我比较喜欢用 Vim 写代码，感觉效率更高，已经用了好几年了"),
            AIMessage(content="Vim 确实很高效，它的模态编辑设计让操作更加流畅"),
        ]
        result = manager.auto_save(messages)
        assert len(result) == 1
        assert memory_store.count() == 1

    def test_saves_nothing_when_empty_array(self, memory_store):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "[]"
        llm.invoke.return_value = resp
        manager = MemoryManager(store=memory_store, llm=llm)

        messages = [HumanMessage(content="今天天气真好啊" * 10)]
        result = manager.auto_save(messages)
        assert result == []
        assert memory_store.count() == 0

    def test_handles_markdown_wrapped_json(self, memory_store):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = '```json\n[{"content": "test", "memory_type": "fact", "tags": []}]\n```'
        llm.invoke.return_value = resp
        manager = MemoryManager(store=memory_store, llm=llm)

        messages = [HumanMessage(content="这是一段足够长的对话内容" * 10)]
        result = manager.auto_save(messages)
        assert len(result) == 1

    def test_handles_invalid_json_gracefully(self, memory_store):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "not valid json at all"
        llm.invoke.return_value = resp
        manager = MemoryManager(store=memory_store, llm=llm)

        messages = [HumanMessage(content="这是一段足够长的对话内容" * 10)]
        result = manager.auto_save(messages)
        assert result == []

    def test_no_llm_returns_empty(self, memory_store):
        manager = MemoryManager(store=memory_store, llm=None)
        messages = [HumanMessage(content="很长的对话" * 20)]
        result = manager.auto_save(messages)
        assert result == []


class TestSummarizeForInjection:
    def test_truncates_long_context(self, memory_store):
        memory_store.save(MemoryRecord(content="x" * 500, memory_type="fact"))
        manager = MemoryManager(store=memory_store)
        result = manager.summarize_for_injection("x", max_chars=100)
        assert len(result) <= 120  # 100 + "...(记忆已截断)"

    def test_returns_empty_when_no_memories(self, memory_store):
        manager = MemoryManager(store=memory_store)
        assert manager.summarize_for_injection("anything") == ""
