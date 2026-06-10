"""main.py — deal_command 测试"""

from unittest.mock import MagicMock

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.main import deal_command


class TestDealCommand:
    def setup_method(self):
        self.graph = MagicMock()
        self.config = {"configurable": {"thread_id": "test"}}

    def test_memory_command_with_records(self, capsys):
        store = SQLiteMemoryStore(db_path=":memory:")
        store.save(MemoryRecord(content="测试记忆", memory_type="fact"))

        result = deal_command(self.graph, self.config, "/memory", memory_store=store)
        assert result is True
        captured = capsys.readouterr()
        assert "测试记忆" in captured.out

    def test_memory_command_no_records(self, capsys):
        store = SQLiteMemoryStore(db_path=":memory:")

        result = deal_command(self.graph, self.config, "/memory", memory_store=store)
        assert result is True
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_unknown_command_returns_false(self):
        store = SQLiteMemoryStore(db_path=":memory:")
        result = deal_command(self.graph, self.config, "/unknown", memory_store=store)
        assert result is False
