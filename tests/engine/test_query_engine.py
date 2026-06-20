"""engine.query_engine — QueryEngine 测试"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk

from LangCode.engine.query_engine import (
    EngineEvent, QueryEngineConfig, QueryEngine,
)


# ── 辅助 ──

def make_mock_graph(messages=None):
    """创建模拟的 LangGraph CompiledStateGraph"""
    graph = MagicMock()
    state_values = {"messages": messages or []}
    graph.get_state.return_value = MagicMock(values=state_values)
    graph.stream.return_value = iter([])  # 空事件流
    return graph


def make_engine(graph=None, **kwargs):
    """创建测试用 QueryEngine"""
    graph = graph or make_mock_graph()
    cfg = QueryEngineConfig(
        workspace_dir="/tmp/ws",
        graph=graph,
        config={"configurable": {"thread_id": "test-thread"}},
        agent_prompt="你是测试 Agent",
        platform_prompt="平台信息",
        **kwargs,
    )
    return QueryEngine(cfg)


# ── EngineEvent ──

class TestEngineEvent:
    def test_basic(self):
        e = EngineEvent(type="text_chunk", data="hello")
        assert e.type == "text_chunk"
        assert e.data == "hello"
        assert e.meta == {}

    def test_default_meta(self):
        e = EngineEvent(type="done")
        assert e.meta == {}


# ── _ensure_initialized ──

class TestEnsureInitialized:
    def test_injects_system_prompts_on_new_session(self):
        graph = make_mock_graph(messages=[])
        engine = make_engine(graph=graph)

        engine._ensure_initialized()

        # 验证 update_state 被调用注入系统消息
        graph.update_state.assert_called_once()
        call_args = graph.update_state.call_args
        injected = call_args[0][1]["messages"]
        assert len(injected) == 2  # platform_prompt + agent_prompt
        assert any("平台" in m.content for m in injected)
        assert any("测试 Agent" in m.content for m in injected)

    def test_skips_initialization_on_existing_session(self):
        graph = make_mock_graph(messages=[HumanMessage(content="已有消息")])
        engine = make_engine(graph=graph)

        engine._ensure_initialized()
        graph.update_state.assert_not_called()

    def test_idempotent(self):
        graph = make_mock_graph(messages=[])
        engine = make_engine(graph=graph)

        engine._ensure_initialized()
        engine._ensure_initialized()  # 第二次不应再调用
        assert graph.update_state.call_count == 1


# ── _consume_events ──

class TestConsumeEvents:
    def test_empty_events_yields_done(self):
        engine = make_engine()
        events = list(engine._consume_events(iter([])))
        assert len(events) == 1
        assert events[0].type == "done"

    def test_text_chunk_event(self):
        engine = make_engine()
        chunk = AIMessageChunk(content="你好")
        raw_events = [("messages", (chunk, {}))]
        events = list(engine._consume_events(iter(raw_events)))
        text_events = [e for e in events if e.type == "text_chunk"]
        assert len(text_events) == 1
        assert text_events[0].data == "你好"

    def test_tool_call_event(self):
        engine = make_engine()
        ai_msg = AIMessage(content="", tool_calls=[{
            "id": "tc1", "name": "read_file", "args": {"file_path": "x.py"},
        }])
        raw_events = [("updates", {"agent": {"messages": [ai_msg]}})]
        events = list(engine._consume_events(iter(raw_events)))
        tc_events = [e for e in events if e.type == "tool_call"]
        assert len(tc_events) == 1
        assert tc_events[0].data["name"] == "read_file"

    def test_tool_result_event(self):
        engine = make_engine()
        tool_msg = MagicMock()
        tool_msg.name = "read_file"
        tool_msg.content = "file content here"
        raw_events = [("updates", {"tools": {"messages": [tool_msg]}})]
        events = list(engine._consume_events(iter(raw_events)))
        tr_events = [e for e in events if e.type == "tool_result"]
        assert len(tr_events) == 1
        assert tr_events[0].data["name"] == "read_file"

    def test_route_event(self):
        engine = make_engine()
        raw_events = [("updates", {"router": {"route": "explore"}})]
        events = list(engine._consume_events(iter(raw_events)))
        route_events = [e for e in events if e.type == "route"]
        assert len(route_events) == 1
        assert route_events[0].data == "explore"

    def test_verify_pass_event(self):
        engine = make_engine()
        raw_events = [("updates", {"auto_verify": {"verify_errors": None}})]
        events = list(engine._consume_events(iter(raw_events)))
        verify_events = [e for e in events if e.type == "verify"]
        assert len(verify_events) == 1
        assert verify_events[0].data["status"] == "pass"

    def test_verify_fail_event(self):
        engine = make_engine()
        raw_events = [("updates", {"auto_verify": {"verify_errors": ["syntax error"]}})]
        events = list(engine._consume_events(iter(raw_events)))
        verify_events = [e for e in events if e.type == "verify"]
        assert verify_events[0].data["status"] == "fail"
        assert "syntax error" in verify_events[0].data["errors"]

    def test_plan_event(self):
        engine = make_engine()
        raw_events = [("updates", {"mark_step": {"current_plan": {}}})]
        events = list(engine._consume_events(iter(raw_events)))
        plan_events = [e for e in events if e.type == "plan"]
        assert len(plan_events) == 1

    def test_interrupt_event_stops_stream(self):
        engine = make_engine()
        interrupt_obj = MagicMock()
        interrupt_obj.value = "请确认是否继续"
        raw_events = [("updates", {"__interrupt__": [interrupt_obj]})]
        events = list(engine._consume_events(iter(raw_events)))
        int_events = [e for e in events if e.type == "interrupt"]
        assert len(int_events) == 1
        # 中断后不应有 done 事件
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 0

    def test_exception_yields_error(self):
        engine = make_engine()

        def bad_events():
            raise RuntimeError("stream failed")
            yield  # make it a generator

        events = list(engine._consume_events(bad_events()))
        assert any(e.type == "error" for e in events)

    def test_mixed_events(self):
        """多种事件混合：text → tool_call → tool_result → done"""
        engine = make_engine()
        ai_msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read", "args": {}}])
        tool_msg = MagicMock()
        tool_msg.name = "read"
        tool_msg.content = "result"

        raw_events = [
            ("messages", (AIMessageChunk(content="让我看看"), {})),
            ("updates", {"agent": {"messages": [ai_msg]}}),
            ("updates", {"tools": {"messages": [tool_msg]}}),
        ]
        events = list(engine._consume_events(iter(raw_events)))
        types = [e.type for e in events]
        assert "text_chunk" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "done" in types


# ── submit_message ──

class TestSubmitMessage:
    def test_yields_done_on_empty_stream(self):
        graph = make_mock_graph(messages=[])
        graph.stream.return_value = iter([])
        engine = make_engine(graph=graph)

        events = list(engine.submit_message("hello"))
        assert events[-1].type == "done"

    def test_calls_graph_stream_with_user_message(self):
        graph = make_mock_graph(messages=[])
        graph.stream.return_value = iter([])
        engine = make_engine(graph=graph)

        list(engine.submit_message("测试消息"))

        graph.stream.assert_called_once()
        call_args = graph.stream.call_args[0]
        state_update = call_args[0]
        assert any(isinstance(m, HumanMessage) and "测试消息" in m.content
                    for m in state_update["messages"])

    def test_injects_memory_context(self):
        graph = make_mock_graph(messages=[])
        graph.stream.return_value = iter([])

        memory_manager = MagicMock()
        memory_manager.get_context.return_value = "相关记忆内容"
        engine = make_engine(graph=graph, memory_manager=memory_manager)

        list(engine.submit_message("查询"))

        memory_manager.get_context.assert_called_once_with("查询")
        graph.update_state.assert_any_call(
            engine.config, {"memory_context": "相关记忆内容"}
        )


# ── close ──

class TestClose:
    def test_close_releases_connection(self):
        engine = make_engine()
        mock_conn = MagicMock()
        engine._ckpt_conn = mock_conn
        engine.close()
        mock_conn.close.assert_called_once()
        assert engine._ckpt_conn is None

    def test_close_noop_without_connection(self):
        engine = make_engine()
        engine.close()  # 不应抛异常
