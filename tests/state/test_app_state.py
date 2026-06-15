"""state.app_state — 全局应用状态测试"""

import pytest
from dataclasses import replace

from LangCode.state.app_state import (
    AppState, UserInfo, SessionConfig, AnalyticsSnapshot,
    init_app_state, get_app_state, update_app_state, subscribe_app_state,
    _app_state_store,
)


@pytest.fixture(autouse=True)
def reset_app_state():
    """每个测试前重置全局单例"""
    import LangCode.state.app_state as mod
    mod._app_state_store = None
    yield
    mod._app_state_store = None


class TestAppStateDefaults:
    def test_user_defaults(self):
        u = UserInfo()
        assert u.platform == "linux"
        assert u.name == ""
        assert u.home_dir == ""

    def test_session_defaults(self):
        s = SessionConfig()
        assert s.agent_mode == "default"
        assert s.auto_verify is True
        assert s.max_turns == 50
        assert s.token_budget is None
        assert s.workspace_dir == ""

    def test_analytics_defaults(self):
        a = AnalyticsSnapshot()
        assert a.total_tool_calls == 0
        assert a.total_api_calls == 0
        assert a.total_tokens_used == 0


class TestAppStateInit:
    def test_init_creates_store(self):
        state = init_app_state(platform="windows", workspace_dir="/tmp/test")
        assert state.user.platform == "windows"
        assert state.session.workspace_dir == "/tmp/test"
        assert state.session.agent_mode == "default"

    def test_get_after_init(self):
        init_app_state()
        s = get_app_state()
        assert isinstance(s, AppState)
        assert s.session.agent_mode == "default"

    def test_get_before_init_raises(self):
        with pytest.raises(RuntimeError, match="尚未初始化"):
            get_app_state()


class TestAppStateUpdate:
    def test_update_agent_mode(self):
        init_app_state()
        update_app_state(lambda prev: replace(prev, session=replace(prev.session, agent_mode="plan")))
        s = get_app_state()
        assert s.session.agent_mode == "plan"

    def test_update_preserves_other_fields(self):
        init_app_state(platform="windows")
        update_app_state(lambda prev: replace(prev, session=replace(prev.session, max_turns=100)))
        s = get_app_state()
        assert s.session.max_turns == 100
        assert s.user.platform == "windows"

    def test_update_before_init_raises(self):
        with pytest.raises(RuntimeError, match="尚未初始化"):
            update_app_state(lambda x: x)


class TestAppStateSubscribe:
    def test_subscribe_receives_updates(self):
        init_app_state()
        calls = []
        unsub = subscribe_app_state(lambda: calls.append(get_app_state().session.agent_mode))
        update_app_state(lambda prev: replace(prev, session=replace(prev.session, agent_mode="bypass")))
        assert calls == ["bypass"]
        unsub()

    def test_unsubscribe(self):
        init_app_state()
        calls = []
        unsub = subscribe_app_state(lambda: calls.append(1))
        update_app_state(lambda prev: replace(prev, session=replace(prev.session, agent_mode="plan")))
        unsub()
        update_app_state(lambda prev: replace(prev, session=replace(prev.session, agent_mode="default")))
        assert calls == [1]

    def test_subscribe_before_init_raises(self):
        with pytest.raises(RuntimeError):
            subscribe_app_state(lambda: None)
