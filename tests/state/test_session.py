"""state.session — SessionStore 测试"""

import pytest
from LangCode.state.session import SessionStore, SessionRecord


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "sessions.db"
    return SessionStore(db_path=str(db))


class TestSessionRecord:
    def test_defaults(self):
        r = SessionRecord(workspace="/tmp")
        assert len(r.id) == 12
        assert r.title == "新对话"
        assert r.created_at is not None

    def test_custom_fields(self):
        r = SessionRecord(id="abc123", workspace="/ws", title="测试会话")
        assert r.id == "abc123"
        assert r.title == "测试会话"


class TestSessionStore:
    def test_save_and_get(self, store):
        record = SessionRecord(id="s1", workspace="/ws", title="第一次对话")
        store.save(record)

        got = store.get("s1", "/ws")
        assert got is not None
        assert got.id == "s1"
        assert got.title == "第一次对话"

    def test_get_nonexistent(self, store):
        assert store.get("no_such_id", "/ws") is None

    def test_get_wrong_workspace(self, store):
        store.save(SessionRecord(id="s1", workspace="/ws1"))
        assert store.get("s1", "/ws2") is None

    def test_save_upsert_updates_title(self, store):
        store.save(SessionRecord(id="s1", workspace="/ws", title="旧标题"))
        store.save(SessionRecord(id="s1", workspace="/ws", title="新标题"))
        got = store.get("s1", "/ws")
        assert got.title == "新标题"

    def test_list_sessions_ordered_by_updated_at(self, store):
        store.save(SessionRecord(id="s1", workspace="/ws", title="第一个"))
        store.save(SessionRecord(id="s2", workspace="/ws", title="第二个"))
        sessions = store.list_sessions("/ws")
        assert len(sessions) == 2
        # 最新更新的排前面
        assert sessions[0].id == "s2"

    def test_list_sessions_limit(self, store):
        for i in range(5):
            store.save(SessionRecord(id=f"s{i}", workspace="/ws"))
        sessions = store.list_sessions("/ws", limit=3)
        assert len(sessions) == 3

    def test_list_sessions_isolated_by_workspace(self, store):
        store.save(SessionRecord(id="s1", workspace="/ws1"))
        store.save(SessionRecord(id="s2", workspace="/ws2"))
        assert len(store.list_sessions("/ws1")) == 1
        assert len(store.list_sessions("/ws2")) == 1

    def test_delete_existing(self, store):
        store.save(SessionRecord(id="s1", workspace="/ws"))
        assert store.delete("s1", "/ws") is True
        assert store.get("s1", "/ws") is None

    def test_delete_nonexistent(self, store):
        assert store.delete("no_such", "/ws") is False

    def test_empty_list(self, store):
        assert store.list_sessions("/ws") == []
