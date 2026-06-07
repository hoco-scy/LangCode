"""memory/store.py — SQLiteMemoryStore + MemoryRecord 测试"""

import pytest
from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord


class TestMemoryRecord:
    def test_default_values(self):
        r = MemoryRecord(content="test", memory_type="fact")
        assert r.content == "test"
        assert r.memory_type == "fact"
        assert r.tags == []
        assert r.access_count == 0
        assert len(r.id) == 12

    def test_custom_tags(self):
        r = MemoryRecord(content="c", memory_type="preference", tags=["python", "style"])
        assert r.tags == ["python", "style"]

    def test_serialization(self):
        r = MemoryRecord(content="c", memory_type="fact")
        data = r.model_dump()
        restored = MemoryRecord(**data)
        assert restored.id == r.id


class TestSQLiteMemoryStore:
    def test_save_and_retrieve(self, memory_store):
        r = MemoryRecord(content="Python 是最好的语言", memory_type="fact")
        rid = memory_store.save(r)
        assert rid == r.id
        assert memory_store.count() == 1

    def test_search_fts(self, memory_store):
        memory_store.save(MemoryRecord(content="Python 编程很有趣", memory_type="fact"))
        memory_store.save(MemoryRecord(content="Java 也很流行", memory_type="fact"))
        results = memory_store.search("Python")
        assert len(results) >= 1
        assert any("Python" in r.content for r in results)

    def test_search_no_results(self, memory_store):
        results = memory_store.search("不存在的关键词")
        assert results == []

    def test_search_special_chars_fallback(self, memory_store):
        memory_store.save(MemoryRecord(content="test@#$%", memory_type="fact"))
        results = memory_store.search("@#$")
        # LIKE 降级搜索
        assert isinstance(results, list)

    def test_list_all(self, memory_store):
        memory_store.save(MemoryRecord(content="a", memory_type="fact"))
        memory_store.save(MemoryRecord(content="b", memory_type="preference"))
        all_records = memory_store.list_all()
        assert len(all_records) == 2

    def test_list_all_filter_type(self, memory_store):
        memory_store.save(MemoryRecord(content="a", memory_type="fact"))
        memory_store.save(MemoryRecord(content="b", memory_type="preference"))
        facts = memory_store.list_all(memory_type="fact")
        assert len(facts) == 1
        assert facts[0].memory_type == "fact"

    def test_delete_existing(self, memory_store):
        r = MemoryRecord(content="to delete", memory_type="fact")
        memory_store.save(r)
        assert memory_store.delete(r.id) is True
        assert memory_store.count() == 0

    def test_delete_nonexistent(self, memory_store):
        assert memory_store.delete("no_such_id") is False

    def test_count(self, memory_store):
        assert memory_store.count() == 0
        memory_store.save(MemoryRecord(content="a", memory_type="fact"))
        assert memory_store.count() == 1
        memory_store.save(MemoryRecord(content="b", memory_type="fact"))
        assert memory_store.count() == 2

    def test_save_updates_existing(self, memory_store):
        r = MemoryRecord(content="original", memory_type="fact")
        memory_store.save(r)
        r.content = "updated"
        memory_store.save(r)
        assert memory_store.count() == 1
        results = memory_store.search("updated")
        assert len(results) == 1

    def test_search_updates_access_count(self, memory_store):
        r = MemoryRecord(content="Python 好", memory_type="fact")
        memory_store.save(r)
        results = memory_store.search("Python")
        assert results[0].access_count == 1

    def test_full_workflow(self, memory_store):
        """完整工作流：保存多条 → 搜索 → 列出 → 删除"""
        for i in range(5):
            memory_store.save(MemoryRecord(
                content=f"记忆 {i}: {'Python' if i % 2 == 0 else 'Java'} 编程",
                memory_type="fact" if i < 3 else "skill",
            ))
        assert memory_store.count() == 5

        py_results = memory_store.search("Python")
        assert len(py_results) >= 2

        facts = memory_store.list_all(memory_type="fact")
        assert len(facts) == 3

        memory_store.delete(py_results[0].id)
        assert memory_store.count() == 4
