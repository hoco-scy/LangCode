"""cli.repl — REPL 辅助函数测试"""

import pytest
from unittest.mock import MagicMock, patch
from io import StringIO

from LangCode.engine.query_engine import EngineEvent
from LangCode.cli.repl import _consume_and_print, _sync_title


class TestConsumeAndPrint:
    def test_text_chunk_prints_content(self, capsys):
        events = [EngineEvent(type="text_chunk", data="Hello")]
        _consume_and_print(iter(events))
        assert capsys.readouterr().out == "Hello"

    def test_multiple_text_chunks_concatenated(self, capsys):
        events = [
            EngineEvent(type="text_chunk", data="Hello "),
            EngineEvent(type="text_chunk", data="World"),
        ]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "Hello World" in output

    def test_done_stops_processing(self, capsys):
        events = [
            EngineEvent(type="text_chunk", data="before"),
            EngineEvent(type="done"),
            EngineEvent(type="text_chunk", data="after"),  # 不应被处理
        ]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "before" in output
        assert "after" not in output

    def test_tool_call_prints_name(self, capsys):
        events = [EngineEvent(type="tool_call", data={"name": "read_file", "args": {"file_path": "x.py"}})]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "read_file" in output

    def test_tool_result_prints_content(self, capsys):
        events = [EngineEvent(type="tool_result", data={"name": "read_file", "content": "file content"})]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "read_file" in output

    def test_route_event(self, capsys):
        events = [EngineEvent(type="route", data="explore")]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "explore" in output

    def test_verify_pass(self, capsys):
        events = [EngineEvent(type="verify", data={"status": "pass"})]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "通过" in output

    def test_verify_fail(self, capsys):
        events = [EngineEvent(type="verify", data={"status": "fail", "errors": ["e1", "e2"]})]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "2" in output  # 2 个错误

    def test_error_event(self, capsys):
        events = [EngineEvent(type="error", data="something went wrong")]
        _consume_and_print(iter(events))
        output = capsys.readouterr().out
        assert "something went wrong" in output

    def test_empty_events(self, capsys):
        _consume_and_print(iter([]))
        # 不应崩溃


class TestSyncTitle:
    def test_syncs_first_human_message(self):
        engine = MagicMock()
        engine.cfg.session_store = MagicMock()
        engine.cfg.current_session = MagicMock()
        engine.get_current_state.return_value = {
            "messages": [
                MagicMock(type="human", content="帮我写一个计算器程序"),
                MagicMock(type="ai", content="好的"),
            ]
        }

        _sync_title(engine)
        assert "计算器" in engine.cfg.current_session.title
        engine.cfg.session_store.save.assert_called_once()

    def test_no_session_store_skips(self):
        engine = MagicMock()
        engine.cfg.session_store = None
        _sync_title(engine)  # 不应崩溃

    def test_no_human_messages_keeps_default_title(self):
        engine = MagicMock()
        engine.cfg.session_store = MagicMock()
        engine.cfg.current_session = MagicMock()
        engine.cfg.current_session.title = "新对话"
        engine.get_current_state.return_value = {"messages": [MagicMock(type="ai", content="hi")]}
        _sync_title(engine)
        # 无 human 消息时 title 不变，但 save 仍会调用
        assert engine.cfg.current_session.title == "新对话"
