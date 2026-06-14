"""state.compact — 上下文压缩器测试"""

import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from LangCode.state.compact import (
    ContextCompactor, CompactResult, estimate_message_tokens,
    MICRO_COMPACT_MAX_CHARS, MICRO_COMPACT_KEEP_RECENT,
    AUTOCOMPACT_BUFFER_TOKENS, MAX_CONSECUTIVE_COMPACT_FAILURES,
)


# ── 辅助工厂 ──

def make_human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def make_ai(text: str = "", tool_calls: list = None) -> AIMessage:
    return AIMessage(content=text, tool_calls=tool_calls or [])


def make_tool(name: str, content: str) -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id="tc_1")


def make_system(text: str) -> SystemMessage:
    return SystemMessage(content=text)


# ── estimate_message_tokens 测试 ──

class TestEstimateTokens:
    def test_empty(self):
        assert estimate_message_tokens([]) == 0

    def test_single_message(self):
        msgs = [make_human("hello world")]  # 11 chars / 4 ≈ 2
        assert estimate_message_tokens(msgs) >= 2

    def test_multiple_messages(self):
        msgs = [make_human("a" * 100), make_ai("b" * 200)]
        tokens = estimate_message_tokens(msgs)
        assert tokens == (100 + 200) // 4

    def test_list_content(self):
        msg = AIMessage(content=[{"type": "text", "text": "hello"}])
        tokens = estimate_message_tokens([msg])
        assert tokens >= 1

    def test_tool_calls_counted(self):
        msg = make_ai("", tool_calls=[{"name": "test", "args": {"key": "value"}, "id": "tc_1"}])
        tokens = estimate_message_tokens([msg])
        assert tokens > 0

    def test_system_messages_counted(self):
        msgs = [make_system("system prompt")]
        tokens = estimate_message_tokens(msgs)
        assert tokens > 0


# ── ContextCompactor 测试 ──

class TestContextCompactorBasic:
    def test_init(self):
        c = ContextCompactor()
        assert c.consecutive_failures == 0

    def test_get_effective_window(self):
        c = ContextCompactor(model_name="mimo-v2.5-pro")
        window = c.get_effective_window()
        assert window == 128_000 - 20_000

    def test_get_auto_compact_threshold(self):
        c = ContextCompactor(model_name="mimo-v2.5-pro")
        threshold = c.get_auto_compact_threshold()
        assert threshold == (128_000 - 20_000) - AUTOCOMPACT_BUFFER_TOKENS

    def test_should_compact_below(self):
        c = ContextCompactor(model_name="mimo-v2.5-pro")
        assert c.should_compact([], 1000) is False

    def test_should_compact_above(self):
        c = ContextCompactor(model_name="mimo-v2.5-pro")
        threshold = c.get_auto_compact_threshold()
        assert c.should_compact([], threshold + 1) is True


class TestMicroCompact:
    def test_short_messages_unchanged(self):
        c = ContextCompactor()
        msgs = [make_human("hello"), make_ai("world")]
        result = c.micro_compact(msgs)
        assert len(result) == 2
        assert result[0].content == "hello"

    def test_long_tool_output_trimmed(self):
        c = ContextCompactor()
        long_content = "x" * (MICRO_COMPACT_MAX_CHARS + 1000)
        # Need enough messages so the tool message falls outside
        # the MICRO_COMPACT_KEEP_RECENT window (keep_recent=5).
        # Tool at index 8, total=10, cutoff=5 → 8 >= 5 so still in recent.
        # Tool at index 4, total=10, cutoff=5 → 4 < 5 so NOT in recent.
        # But we need len(msgs) - KEEP_RECENT > tool_index.
        # Put tool at index 3, add 7 trailing → total=10, cutoff=5, 3 < 5 ✓
        msgs = [
            make_human("h1"),
            make_ai("a1"),
            make_human("h2"),
            make_ai("", tool_calls=[{"name": "read_file", "args": {}, "id": "tc_1"}]),
            make_tool("read_file", long_content),
            make_ai("ok"),
            make_human("next"),
            make_ai("response"),
            make_human("h3"),
            make_ai("a3"),
        ]
        result = c.micro_compact(msgs)
        # 工具消息应被裁剪 (at index 4)
        tool_msg = result[4]
        assert "[Old tool result content cleared]" in tool_msg.content
        assert len(tool_msg.content) < len(long_content)

    def test_recent_messages_not_trimmed(self):
        c = ContextCompactor()
        long_content = "x" * (MICRO_COMPACT_MAX_CHARS + 1000)
        msgs = [make_tool("read_file", long_content)]
        # 只有1条消息，少于 KEEP_RECENT，不应裁剪
        result = c.micro_compact(msgs)
        assert result[0].content == long_content

    def test_non_compactable_tool_not_trimmed(self):
        c = ContextCompactor()
        long_content = "x" * (MICRO_COMPACT_MAX_CHARS + 1000)
        msgs = [
            make_human("h1"),
            make_ai("a1"),
            make_human("h2"),
            make_ai("", tool_calls=[{"name": "custom_tool", "args": {}, "id": "tc_1"}]),
            make_tool("custom_tool", long_content),
            make_ai("ok"),
            make_human("next"),
            make_ai("response"),
            make_human("h3"),
            make_ai("a3"),
        ]
        result = c.micro_compact(msgs)
        # custom_tool 不在 COMPACTABLE_TOOLS 中，不应裁剪
        assert result[4].content == long_content

    def test_error_messages_also_trimmed(self):
        c = ContextCompactor()
        error_content = "[Error] something went wrong: " + "x" * (MICRO_COMPACT_MAX_CHARS + 500)
        msgs = [
            make_human("h1"),
            make_ai("a1"),
            make_human("h2"),
            make_ai("", tool_calls=[{"name": "execute_shell", "args": {}, "id": "tc_1"}]),
            make_tool("execute_shell", error_content),
            make_ai("ok"),
            make_human("next"),
            make_ai("response"),
            make_human("h3"),
            make_ai("a3"),
        ]
        result = c.micro_compact(msgs)
        # execute_shell 在 COMPACTABLE_TOOLS 中，错误消息也被裁剪
        assert "[Old tool result content cleared]" in result[4].content


class TestAutoCompact:
    def test_no_system_messages(self):
        c = ContextCompactor()
        msgs = [make_human("hello"), make_ai("world")]
        result = c.auto_compact(msgs)
        assert result.was_compacted is False

    def test_circuit_breaker(self):
        c = ContextCompactor()
        c.consecutive_failures = MAX_CONSECUTIVE_COMPACT_FAILURES
        msgs = [make_system("sys"), make_human("hello")]
        result = c.auto_compact(msgs)
        assert result.was_compacted is False

    def test_with_mock_llm(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "这是对话摘要"
        mock_llm.invoke.return_value = mock_response

        c = ContextCompactor(llm=mock_llm)
        msgs = [
            make_system("system"),
            make_human("msg1"), make_ai("reply1"),
            make_human("msg2"), make_ai("reply2"),
            make_human("msg3"), make_ai("reply3"),
            make_human("msg4"), make_ai("reply4"),
            make_human("msg5"), make_ai("reply5"),
            make_human("msg6"), make_ai("reply6"),
            make_human("msg7"), make_ai("reply7"),
            make_human("msg8"), make_ai("reply8"),
            make_human("msg9"), make_ai("reply9"),
            make_human("msg10"), make_ai("reply10"),
            make_human("msg11"), make_ai("reply11"),
        ]
        result = c.auto_compact(msgs)
        assert result.was_compacted is True
        assert result.strategy == "auto"
        assert result.messages_after < result.messages_before
        # 验证摘要消息存在
        contents = [m.content for m in result.output if hasattr(m, "content")]
        assert any("对话摘要" in str(c) for c in contents)

    def test_failures_increment(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("API error")

        c = ContextCompactor(llm=mock_llm)
        msgs = [make_system("sys")]
        for i in range(12):
            msgs.append(make_human(f"h{i}"))
            msgs.append(make_ai(f"a{i}"))
        c.auto_compact(msgs)
        assert c.consecutive_failures == 1

    def test_success_resets_failures(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "summary"

        c = ContextCompactor(llm=mock_llm)
        c.consecutive_failures = 2
        msgs = [make_system("sys")]
        for i in range(12):
            msgs.append(make_human(f"h{i}"))
            msgs.append(make_ai(f"a{i}"))
        c.auto_compact(msgs)
        assert c.consecutive_failures == 0


class TestCompact:
    def test_compact_micro_only(self):
        c = ContextCompactor(model_name="mimo-v2.5-pro")
        msgs = [make_human("short")]
        result = c.compact(msgs)
        assert result.was_compacted is False

    def test_compact_with_mock_llm(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "summary"

        c = ContextCompactor(llm=mock_llm, model_name="mimo-v2.5-pro")
        # 需要足够多的消息让 should_compact 返回 True
        msgs = [make_system("sys")]
        for i in range(20):
            msgs.append(make_human(f"msg{i} " + "x" * 2000))
            msgs.append(make_ai(f"reply{i} " + "y" * 2000))

        # 手动覆盖 should_compact 让它返回 True
        c.should_compact = lambda m, t: True
        result = c.compact(msgs)
        assert result.was_compacted is True
