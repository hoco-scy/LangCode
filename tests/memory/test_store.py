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

    def test_search_chinese(self, memory_store):
        """FTS5 默认 tokenizer 不支持 CJK 分词，需降级为 LIKE"""
        memory_store.save(MemoryRecord(content="测试记忆系统功能：LangCode 的记忆工具", memory_type="fact"))
        memory_store.save(MemoryRecord(content="Python 是一种编程语言", memory_type="fact"))
        # 搜索中文词（FTS5 无法分词，必须走 LIKE 降级）
        results = memory_store.search("记忆系统")
        assert len(results) == 1
        assert "记忆系统" in results[0].content
        # 搜索英文仍正常工作
        results = memory_store.search("Python")
        assert len(results) >= 1

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


class TestSQLiteMemoryStoreThreading:
    """多线程场景测试 — 模拟 TUI 模式下主线程创建 store，后台线程访问"""

    def test_cross_thread_access(self, memory_store):
        """主线程创建 store，子线程调用方法不报错"""
        import threading

        errors = []
        results = []

        def run_in_thread():
            try:
                memory_store.save(MemoryRecord(content="cross-thread memory", memory_type="fact"))
                results.append(memory_store.count())
                results.append(memory_store.search("cross-thread"))
                results.append(memory_store.list_all())
            except Exception as e:
                errors.append(str(e))

        t = threading.Thread(target=run_in_thread)
        t.start()
        t.join()

        assert errors == [], f"跨线程访问失败: {errors}"
        assert results[0] == 1
        assert len(results[1]) == 1
        assert len(results[2]) == 1

    def test_concurrent_writes(self, memory_store):
        """多个线程同时写入，Lock 保证数据一致"""
        import threading

        num_threads = 5
        writes_per_thread = 20
        barrier = threading.Barrier(num_threads)

        def writer(thread_id):
            barrier.wait()  # 让所有线程同时开始
            for i in range(writes_per_thread):
                memory_store.save(MemoryRecord(
                    content=f"thread-{thread_id}-item-{i}",
                    memory_type="fact",
                ))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert memory_store.count() == num_threads * writes_per_thread

    def test_concurrent_reads_and_writes(self, memory_store):
        """读写并发，不会出现异常"""
        import threading

        # 预写入一些数据
        for i in range(10):
            memory_store.save(MemoryRecord(content=f"初始数据 {i}", memory_type="fact"))

        errors = []

        def reader():
            for _ in range(50):
                try:
                    memory_store.search("初始")
                    memory_store.list_all()
                    memory_store.count()
                except Exception as e:
                    errors.append(str(e))

        def writer():
            for i in range(50):
                try:
                    memory_store.save(MemoryRecord(content=f"新数据 {i}", memory_type="fact"))
                except Exception as e:
                    errors.append(str(e))

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
        threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发读写出现异常: {errors}"
        assert memory_store.count() == 60  # 10 预写入 + 50 新写入

    def test_cross_thread_delete(self, memory_store):
        """子线程中删除记录"""
        import threading

        rid = memory_store.save(MemoryRecord(content="待删除", memory_type="fact"))

        def delete_in_thread():
            return memory_store.delete(rid)

        t = threading.Thread(target=delete_in_thread)
        t.start()
        t.join()

        assert memory_store.count() == 0

    def test_tui_pattern(self, memory_store):
        """模拟 TUI 实际使用模式：主线程创建 store → 后台线程执行 graph → 工具调用 store"""
        import threading

        # 模拟 bridge.py 的模式：主线程有 store 引用，传给后台线程
        def background_graph_execution(store, results_collector):
            """模拟 graph.stream 在后台线程执行时调用 memory 工具"""
            store.save(MemoryRecord(content="用户叫 scy", memory_type="fact", tags=["name"]))
            store.save(MemoryRecord(content="偏好 Python", memory_type="preference", tags=["lang"]))
            found = store.search("scy")
            results_collector.append(found)
            all_items = store.list_all()
            results_collector.append(all_items)

        results = []
        t = threading.Thread(
            target=background_graph_execution,
            args=(memory_store, results),
        )
        t.start()
        t.join()

        assert len(results[0]) == 1
        assert results[0][0].content == "用户叫 scy"
        assert len(results[1]) == 2
