"""state.store — 响应式状态容器测试"""

import pytest
from LangCode.state.store import create_store


class TestStore:
    def test_get_state(self):
        s = create_store(42)
        assert s.get_state() == 42

    def test_set_state_basic(self):
        s = create_store(10)
        s.set_state(lambda x: x + 5)
        assert s.get_state() == 15

    def test_set_state_identity_skip(self):
        """is 相等性检查：返回同一对象时不通知"""
        notifications = []
        s = create_store([1, 2, 3], on_change=lambda p: notifications.append(1))
        s.set_state(lambda x: x)  # 返回同一对象
        assert s.get_state() == [1, 2, 3]
        assert notifications == []

    def test_set_state_value_change(self):
        notifications = []
        s = create_store(10, on_change=lambda p: notifications.append(p))
        s.set_state(lambda x: 20)
        assert s.get_state() == 20
        assert len(notifications) == 1
        assert notifications[0]["old_state"] == 10
        assert notifications[0]["new_state"] == 20

    def test_subscribe_receives_notifications(self):
        calls = []
        s = create_store(0)
        unsub = s.subscribe(lambda: calls.append(s.get_state()))
        s.set_state(lambda x: 1)
        s.set_state(lambda x: 2)
        assert calls == [1, 2]
        unsub()

    def test_unsubscribe(self):
        calls = []
        s = create_store(0)
        unsub = s.subscribe(lambda: calls.append(1))
        s.set_state(lambda x: 1)
        unsub()
        s.set_state(lambda x: 2)
        assert calls == [1]

    def test_multiple_subscribers(self):
        a_calls, b_calls = [], []
        s = create_store(0)
        unsub_a = s.subscribe(lambda: a_calls.append(1))
        unsub_b = s.subscribe(lambda: b_calls.append(1))
        s.set_state(lambda x: 1)
        assert a_calls == [1]
        assert b_calls == [1]
        unsub_a()
        unsub_b()

    def test_set_state_with_dict(self):
        s = create_store({"a": 1})
        s.set_state(lambda d: {**d, "b": 2})
        assert s.get_state() == {"a": 1, "b": 2}

    def test_set_state_with_dataclass(self):
        from dataclasses import dataclass, replace

        @dataclass(frozen=True)
        class MyState:
            name: str = "default"
            count: int = 0

        s = create_store(MyState())
        s.set_state(lambda prev: replace(prev, count=5))
        assert s.get_state().count == 5
        assert s.get_state().name == "default"

    def test_on_change_callback_signature(self):
        payload_received = []
        s = create_store(0, on_change=lambda p: payload_received.append(p))
        s.set_state(lambda x: 1)
        assert len(payload_received) == 1
        assert "old_state" in payload_received[0]
        assert "new_state" in payload_received[0]
