"""shared/context.py — 上下文窗口管理测试"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from LangCode.shared.context import (
    estimate_tokens,
    count_message_tokens,
    count_messages_tokens,
    trim_messages,
    summarize_old_messages,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_english_text(self):
        # "Hello world" ≈ 11 chars → ~3 tokens
        tokens = estimate_tokens("Hello world")
        assert 2 <= tokens <= 5

    def test_chinese_text(self):
        # "你好世界" — tiktoken 可能给 4-8 tokens，启发式回退给 ~2
        tokens = estimate_tokens("你好世界")
        assert 1 <= tokens <= 10

    def test_mixed_text(self):
        tokens = estimate_tokens("Hello 你好 world 世界")
        assert tokens > 0


class TestCountMessages:
    def test_single_message(self):
        msg = HumanMessage(content="Hello")
        tokens = count_message_tokens(msg)
        assert tokens > 0

    def test_multiple_messages(self):
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
        ]
        total = count_messages_tokens(messages)
        assert total > count_message_tokens(messages[0])


class TestTrimMessages:
    def test_no_trimming_when_under_limit(self):
        messages = [HumanMessage(content="Hello"), AIMessage(content="Hi")]
        result = trim_messages(messages, max_tokens=10000)
        assert len(result) == 2

    def test_preserves_system_messages(self):
        messages = [
            SystemMessage(content="System prompt"),
            *[HumanMessage(content=f"Message {i}") for i in range(100)],
        ]
        result = trim_messages(messages, max_tokens=500)
        # System message should be preserved
        system_msgs = [m for m in result if isinstance(m, SystemMessage)]
        assert len(system_msgs) >= 1
        assert any("System prompt" in (m.content or "") for m in system_msgs)

    def test_trimming_reduces_message_count(self):
        messages = [
            SystemMessage(content="System"),
            *[HumanMessage(content=f"Message {i} " * 100) for i in range(50)],
        ]
        result = trim_messages(messages, max_tokens=500)
        assert len(result) < len(messages)

    def test_inserts_trim_notice(self):
        messages = [
            SystemMessage(content="System"),
            *[HumanMessage(content=f"Message {i} " * 100) for i in range(50)],
        ]
        result = trim_messages(messages, max_tokens=500)
        trim_notices = [m for m in result if isinstance(m, SystemMessage) and "裁剪" in (m.content or "")]
        assert len(trim_notices) >= 1


class TestSummarizeOldMessages:
    def test_no_summarize_when_under_threshold(self):
        messages = [HumanMessage(content="short")]
        llm = None  # LLM shouldn't be called
        result = summarize_old_messages(messages, llm, max_tokens=100000)
        assert len(result) == 1

    def test_summarize_with_mock_llm(self):
        from unittest.mock import MagicMock
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "这是对话摘要"
        llm.invoke.return_value = resp

        messages = [
            SystemMessage(content="System prompt"),
            *[HumanMessage(content=f"Message {i} " * 200) for i in range(30)],
        ]
        result = summarize_old_messages(messages, llm, keep_recent=5, max_tokens=1000)
        # Should have: system + summary + 5 recent
        assert len(result) < len(messages)
        summary_msgs = [m for m in result if "对话摘要" in (m.content or "")]
        assert len(summary_msgs) >= 1
