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
