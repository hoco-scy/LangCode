"""shared/session.py — SessionStore + SessionRecord 测试"""

import pytest
from LangCode.shared.session import SessionStore, SessionRecord


class TestSessionRecord:
    def test_default_values(self):
        r = SessionRecord(workspace="/proj")
        assert len(r.id) == 12
        assert r.workspace == "/proj"
        assert r.title == "新对话"
        assert r.created_at is not None
        assert r.updated_at is not None

    def test_custom_fields(self):
        r = SessionRecord(id="abc123", workspace="/tmp", title="自定义标题")
        assert r.id == "abc123"
        assert r.title == "自定义标题"

    def test_serialization(self):
        r = SessionRecord(workspace="/proj")
        data = r.model_dump()
        restored = SessionRecord(**data)
        assert restored.id == r.id
        assert restored.workspace == r.workspace


class TestSessionStore:
    def test_save_and_get(self, session_store):
        r = SessionRecord(workspace="/proj", title="测试会话")
        session_store.save(r)

        loaded = session_store.get(r.id, "/proj")
        assert loaded is not None
        assert loaded.id == r.id
        assert loaded.title == "测试会话"

    def test_get_nonexistent(self, session_store):
        assert session_store.get("no_such_id", "/proj") is None

    def test_get_wrong_workspace(self, session_store):
        r = SessionRecord(workspace="/proj")
        session_store.save(r)
        assert session_store.get(r.id, "/other") is None

    def test_save_updates_title(self, session_store):
        r = SessionRecord(workspace="/proj", title="原标题")
        session_store.save(r)
        r.title = "新标题"
        session_store.save(r)

        loaded = session_store.get(r.id, "/proj")
        assert loaded.title == "新标题"

    def test_list_sessions(self, session_store):
        r1 = SessionRecord(workspace="/proj", title="会话1")
        r2 = SessionRecord(workspace="/proj", title="会话2")
        r3 = SessionRecord(workspace="/other", title="其他工作区")
        session_store.save(r1)
        session_store.save(r2)
        session_store.save(r3)

        proj_sessions = session_store.list_sessions("/proj")
        assert len(proj_sessions) == 2
        titles = {s.title for s in proj_sessions}
        assert titles == {"会话1", "会话2"}

    def test_list_sessions_empty(self, session_store):
        assert session_store.list_sessions("/empty") == []

    def test_list_sessions_ordered_by_update(self, session_store):
        import time
        r1 = SessionRecord(workspace="/proj", title="先")
        session_store.save(r1)
        time.sleep(0.05)  # 确保 updated_at 不同
        r2 = SessionRecord(workspace="/proj", title="后")
        session_store.save(r2)

        sessions = session_store.list_sessions("/proj")
        assert sessions[0].title == "后"

    def test_list_sessions_limit(self, session_store):
        for i in range(5):
            session_store.save(SessionRecord(workspace="/proj", title=f"会话{i}"))

        sessions = session_store.list_sessions("/proj", limit=3)
        assert len(sessions) == 3

    def test_delete_existing(self, session_store):
        r = SessionRecord(workspace="/proj")
        session_store.save(r)
        assert session_store.delete(r.id, "/proj") is True
        assert session_store.get(r.id, "/proj") is None

    def test_delete_nonexistent(self, session_store):
        assert session_store.delete("no_such", "/proj") is False

    def test_delete_wrong_workspace(self, session_store):
        r = SessionRecord(workspace="/proj")
        session_store.save(r)
        assert session_store.delete(r.id, "/other") is False
        assert session_store.get(r.id, "/proj") is not None

    def test_workspace_isolation(self, session_store):
        """不同工作区的会话完全隔离"""
        r1 = SessionRecord(workspace="/projA", title="A的会话")
        r2 = SessionRecord(workspace="/projB", title="B的会话")
        session_store.save(r1)
        session_store.save(r2)

        assert len(session_store.list_sessions("/projA")) == 1
        assert len(session_store.list_sessions("/projB")) == 1
        assert session_store.get(r1.id, "/projB") is None
        assert session_store.get(r2.id, "/projA") is None

    def test_save_idempotent(self, session_store):
        """重复 save 同一条记录不会产生重复"""
        r = SessionRecord(workspace="/proj", title="幂等测试")
        session_store.save(r)
        r.title = "更新"
        session_store.save(r)

        sessions = session_store.list_sessions("/proj")
        assert len(sessions) == 1
        assert sessions[0].title == "更新"

    def test_full_workflow(self, session_store):
        """完整工作流：新建多个 → 列出 → 切换（get）→ 删除"""
        sessions = []
        for i in range(3):
            r = SessionRecord(workspace="/proj", title=f"会话{i}")
            session_store.save(r)
            sessions.append(r)

        listed = session_store.list_sessions("/proj")
        assert len(listed) == 3

        target = session_store.get(sessions[1].id, "/proj")
        assert target.title == "会话1"

        session_store.delete(sessions[0].id, "/proj")
        assert len(session_store.list_sessions("/proj")) == 2
