"""state.transcript — Transcript JSONL 持久化测试"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from LangCode.state.transcript import (
    TranscriptWriter, TranscriptReader, SessionMeta,
    _message_to_dict, _dict_to_message, SESSIONS_DIR,
)


class TestMessageSerialization:
    def test_human_message(self):
        msg = HumanMessage(content="hello")
        d = _message_to_dict(msg)
        assert d["type"] == "human"
        assert d["content"] == "hello"

    def test_ai_message_with_tool_calls(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "args": {"path": "x.py"}, "id": "tc1"}],
        )
        d = _message_to_dict(msg)
        assert d["type"] == "ai"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "read_file"

    def test_tool_message(self):
        msg = ToolMessage(content="file content", name="read_file", tool_call_id="tc1")
        d = _message_to_dict(msg)
        assert d["type"] == "tool"
        assert d["name"] == "read_file"
        assert d["tool_call_id"] == "tc1"

    def test_system_message(self):
        msg = SystemMessage(content="system prompt")
        d = _message_to_dict(msg)
        assert d["type"] == "system"
        assert d["content"] == "system prompt"

    def test_roundtrip(self):
        original = HumanMessage(content="test message")
        d = _message_to_dict(original)
        restored = _dict_to_message(d)
        assert restored.content == "test message"
        assert restored.type == "human"

    def test_ai_roundtrip(self):
        original = AIMessage(content="response", tool_calls=[
            {"name": "read_file", "args": {"path": "x.py"}, "id": "tc1"},
        ])
        d = _message_to_dict(original)
        restored = _dict_to_message(d)
        assert restored.content == "response"
        assert len(restored.tool_calls) == 1

    def test_unknown_type_fallback(self):
        d = {"type": "unknown_type", "content": "test"}
        msg = _dict_to_message(d)
        assert msg.content == "test"


class TestTranscriptWriter:
    def test_creates_file(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test123")
            assert writer.file_path == tmp_path / "test123.jsonl"
            uuid = writer.append(HumanMessage(content="hello"))
            assert writer.file_path.exists()
            assert len(uuid) == 12

    def test_append_chains_parent_uuid(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test456")
            uuid1 = writer.append(HumanMessage(content="msg1"))
            uuid2 = writer.append(AIMessage(content="reply1"))

            lines = writer.file_path.read_text().strip().split("\n")
            assert len(lines) == 2

            rec1 = json.loads(lines[0])
            rec2 = json.loads(lines[1])
            assert rec1["parent_uuid"] is None
            assert rec2["parent_uuid"] == uuid1

    def test_explicit_parent_uuid(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test789")
            writer.append(HumanMessage(content="msg1"))
            uuid2 = writer.append(AIMessage(content="reply1"))
            # 第三条显式指定 parent
            uuid3 = writer.append(HumanMessage(content="msg2"), parent_uuid=uuid2)

            lines = writer.file_path.read_text().strip().split("\n")
            rec3 = json.loads(lines[2])
            assert rec3["parent_uuid"] == uuid2

    def test_message_content_preserved(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test_content")
            writer.append(HumanMessage(content="test content abc123"))

            lines = writer.file_path.read_text(encoding="utf-8").strip().split("\n")
            rec = json.loads(lines[0])
            assert rec["message"]["content"] == "test content abc123"

    def test_tool_message_preserved(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test_tool")
            writer.append(ToolMessage(content="result", name="read_file", tool_call_id="tc1"))

            lines = writer.file_path.read_text().strip().split("\n")
            rec = json.loads(lines[0])
            assert rec["message"]["type"] == "tool"
            assert rec["message"]["name"] == "read_file"

    def test_get_last_uuid(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="test_last")
            assert writer.get_last_uuid() is None
            uuid = writer.append(HumanMessage(content="msg"))
            assert writer.get_last_uuid() == uuid


class TestTranscriptReader:
    def test_load_empty(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            reader = TranscriptReader()
            msgs = reader.load("nonexistent")
            assert msgs == []

    def test_load_linear_chain(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="linear")
            writer.append(HumanMessage(content="q1"))
            writer.append(AIMessage(content="a1"))
            writer.append(HumanMessage(content="q2"))
            writer.append(AIMessage(content="a2"))

            reader = TranscriptReader()
            msgs = reader.load("linear")
            assert len(msgs) == 4
            assert msgs[0].content == "q1"
            assert msgs[3].content == "a2"

    def test_list_sessions(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            # 创建两个会话
            w1 = TranscriptWriter(session_id="s1")
            w1.append(HumanMessage(content="hello"))
            w2 = TranscriptWriter(session_id="s2")
            w2.append(HumanMessage(content="world"))

            reader = TranscriptReader()
            sessions = reader.list_sessions()
            assert len(sessions) == 2
            ids = {s.id for s in sessions}
            assert "s1" in ids
            assert "s2" in ids

    def test_delete(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            writer = TranscriptWriter(session_id="to_delete")
            writer.append(HumanMessage(content="msg"))

            reader = TranscriptReader()
            assert reader.delete("to_delete") is True
            assert reader.load("to_delete") == []

    def test_delete_nonexistent(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            reader = TranscriptReader()
            assert reader.delete("nope") is False

    def test_list_sessions_empty(self, tmp_path):
        with patch("LangCode.state.transcript.SESSIONS_DIR", tmp_path):
            reader = TranscriptReader()
            assert reader.list_sessions() == []


class TestSessionMeta:
    def test_create(self):
        meta = SessionMeta(id="abc", title="test", message_count=5)
        assert meta.id == "abc"
        assert meta.title == "test"
        assert meta.message_count == 5

    def test_defaults(self):
        meta = SessionMeta(id="x")
        assert meta.title == "新对话"
        assert meta.message_count == 0
