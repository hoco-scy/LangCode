"""memory/tools.py — memory_save/search/list 工具测试"""

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.memory.manager import MemoryManager
from LangCode.memory.tools import create_memory_tools


class TestMemoryTools:
    def setup_method(self):
        """每个测试前重新初始化"""
        self.store = SQLiteMemoryStore(db_path=":memory:")
        self.manager = MemoryManager(store=self.store)
        self.memory_save, self.memory_search, self.memory_list = create_memory_tools(self.store, self.manager)

    def test_memory_save(self):
        result = self.memory_save.invoke({"content": "用户喜欢 Python", "memory_type": "preference", "tags": ["lang"]})
        assert result["success"] is True
        assert "id" in result
        assert self.store.count() == 1

    def test_memory_save_defaults(self):
        result = self.memory_save.invoke({"content": "事实"})
        assert result["success"] is True
        records = self.store.list_all()
        assert records[0].memory_type == "fact"

    def test_memory_search_found(self):
        self.store.save(MemoryRecord(content="Python 很好用", memory_type="fact"))
        result = self.memory_search.invoke({"query": "Python"})
        assert result["success"] is True
        assert len(result["results"]) >= 1
        assert "Python" in result["results"][0]["content"]

    def test_memory_search_not_found(self):
        result = self.memory_search.invoke({"query": "不存在"})
        assert result["success"] is True
        assert result["results"] == []

    def test_memory_list_all(self):
        self.store.save(MemoryRecord(content="a", memory_type="fact"))
        self.store.save(MemoryRecord(content="b", memory_type="skill"))
        result = self.memory_list.invoke({})
        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["results"]) == 2

    def test_memory_list_filter_type(self):
        self.store.save(MemoryRecord(content="a", memory_type="fact"))
        self.store.save(MemoryRecord(content="b", memory_type="skill"))
        result = self.memory_list.invoke({"memory_type": "skill"})
        assert result["success"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["type"] == "skill"


class TestMemoryToolsThreading:
    """多线程场景 — 模拟 TUI 后台线程调用 memory 工具"""

    def setup_method(self):
        self.store = SQLiteMemoryStore(db_path=":memory:")
        self.manager = MemoryManager(store=self.store)
        self.memory_save, self.memory_search, self.memory_list = create_memory_tools(self.store, self.manager)

    def test_tools_from_background_thread(self):
        """主线程创建 tools，子线程调用 — 模拟 bridge.py 实际场景"""
        import threading

        errors = []
        results = []

        def run_tools():
            try:
                r1 = self.memory_save.invoke({
                    "content": "用户 scy 偏好 Python",
                    "memory_type": "preference",
                    "tags": ["user", "lang"],
                })
                results.append(r1)

                r2 = self.memory_search.invoke({"query": "scy"})
                results.append(r2)

                r3 = self.memory_list.invoke({})
                results.append(r3)
            except Exception as e:
                errors.append(str(e))

        t = threading.Thread(target=run_tools)
        t.start()
        t.join()

        assert errors == [], f"后台线程调用工具失败: {errors}"
        assert results[0]["success"] is True
        assert results[1]["success"] is True
        assert len(results[1]["results"]) == 1
        assert results[2]["success"] is True
        assert results[2]["total"] == 1

    def test_concurrent_tool_calls(self):
        """多个线程同时调用工具，验证线程安全"""
        import threading

        num_threads = 4
        calls_per_thread = 25
        errors = []

        def worker(thread_id):
            for i in range(calls_per_thread):
                try:
                    self.memory_save.invoke({
                        "content": f"thread-{thread_id}-msg-{i}",
                        "memory_type": "fact",
                    })
                    self.memory_search.invoke({"query": f"thread-{thread_id}"})
                    self.memory_list.invoke({})
                except Exception as e:
                    errors.append(f"thread-{thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发工具调用出现异常: {errors}"
        assert self.store.count() == num_threads * calls_per_thread
