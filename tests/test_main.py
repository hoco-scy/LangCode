"""main.py — deal_command 测试"""

from unittest.mock import MagicMock

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.shared.session import SessionStore, SessionRecord
from LangCode.main import deal_command


def _make_session_record(workspace="/proj"):
    return SessionRecord(id="sess001", workspace=workspace, title="测试会话")


class TestDealCommandMemory:
    def setup_method(self):
        self.graph = MagicMock()
        self.config = {"configurable": {"thread_id": "test"}}
        self.session_store = SessionStore(db_path=":memory:")
        self.session = _make_session_record()

    def test_memory_command_with_records(self, capsys):
        store = SQLiteMemoryStore(db_path=":memory:")
        store.save(MemoryRecord(content="测试记忆", memory_type="fact"))

        handled, _, _ = deal_command(
            self.graph, self.config, "/memory",
            memory_store=store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "测试记忆" in captured.out

    def test_memory_command_no_records(self, capsys):
        store = SQLiteMemoryStore(db_path=":memory:")

        handled, _, _ = deal_command(
            self.graph, self.config, "/memory",
            memory_store=store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_unknown_command_returns_false(self):
        store = SQLiteMemoryStore(db_path=":memory:")
        handled, _, _ = deal_command(
            self.graph, self.config, "/unknown",
            memory_store=store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is False


class TestDealCommandSession:
    def setup_method(self):
        self.graph = MagicMock()
        self.graph.get_state.return_value.values = {"messages": [], "current_plan": None}
        self.config = {"configurable": {"thread_id": "sess001"}}
        self.memory_store = SQLiteMemoryStore(db_path=":memory:")
        self.session_store = SessionStore(db_path=":memory:")
        self.session = _make_session_record()

    def test_session_show(self, capsys):
        handled, cur, cfg = deal_command(
            self.graph, self.config, "/session",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        assert cur is self.session
        captured = capsys.readouterr()
        assert "sess001" in captured.out

    def test_session_show_with_plan(self, capsys):
        self.graph.get_state.return_value.values = {
            "messages": ["msg1"],
            "current_plan": {"goal": "test"},
            "plan_step_index": 1,
        }
        handled, _, _ = deal_command(
            self.graph, self.config, "/session",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "计划进行中" in captured.out
        assert "步骤 2" in captured.out

    def test_session_list_empty(self, capsys):
        handled, _, _ = deal_command(
            self.graph, self.config, "/session list",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_session_list_with_sessions(self, capsys):
        self.session_store.save(SessionRecord(workspace="/proj", title="会话A"))
        self.session_store.save(SessionRecord(workspace="/proj", title="会话B"))

        handled, _, _ = deal_command(
            self.graph, self.config, "/session list",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "会话A" in captured.out
        assert "会话B" in captured.out

    def test_session_list_workspace_isolation(self, capsys):
        self.session_store.save(SessionRecord(workspace="/proj", title="proj的"))
        self.session_store.save(SessionRecord(workspace="/other", title="other的"))

        handled, _, _ = deal_command(
            self.graph, self.config, "/session list",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        captured = capsys.readouterr()
        assert "proj的" in captured.out
        assert "other的" not in captured.out

    def test_session_new(self, capsys):
        old_id = self.session.id
        handled, cur, cfg = deal_command(
            self.graph, self.config, "/session new",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        assert cur.id != old_id
        assert cfg["configurable"]["thread_id"] == cur.id
        captured = capsys.readouterr()
        assert "已创建新会话" in captured.out

    def test_session_switch(self, capsys):
        saved = SessionRecord(id="target01", workspace="/proj", title="目标会话")
        self.session_store.save(saved)

        handled, cur, cfg = deal_command(
            self.graph, self.config, "/session target01",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        assert cur.id == "target01"
        assert cfg["configurable"]["thread_id"] == "target01"
        captured = capsys.readouterr()
        assert "已切换到会话" in captured.out

    def test_session_switch_not_found(self, capsys):
        handled, cur, _ = deal_command(
            self.graph, self.config, "/session nonexistent",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        assert cur is self.session  # 未切换
        captured = capsys.readouterr()
        assert "未找到" in captured.out

    def test_session_switch_workspace_guard(self, capsys):
        """不能切换到其他工作区的会话"""
        saved = SessionRecord(id="other01", workspace="/other", title="别人的")
        self.session_store.save(saved)

        handled, cur, _ = deal_command(
            self.graph, self.config, "/session other01",
            memory_store=self.memory_store, session_store=self.session_store,
            current_session=self.session, workspace="/proj",
        )
        assert handled is True
        assert cur is self.session  # 未切换
        captured = capsys.readouterr()
        assert "未找到" in captured.out
