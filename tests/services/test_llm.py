"""services.llm — LLM 客户端测试"""

import pytest
from unittest.mock import MagicMock, patch

from LangCode.services.config import Config, CONFIG_DEFAULTS


def _make_mock_chat_openai(model_name="test-model"):
    """创建一个 mock ChatOpenAI 实例"""
    mock = MagicMock()
    mock.model_name = model_name
    mock.bind_tools.return_value = mock
    mock.with_structured_output.return_value = mock
    return mock


@pytest.fixture
def config():
    return Config([{**CONFIG_DEFAULTS, "model.api_key": "test-key"}])


@pytest.fixture(autouse=True)
def mock_chat_openai():
    """所有测试中 mock ChatOpenAI，避免真实 API 调用"""
    mock_cls = MagicMock(side_effect=lambda **kwargs: _make_mock_chat_openai(kwargs.get("model", "test")))
    with patch("LangCode.services.llm.ChatOpenAI", mock_cls):
        yield mock_cls


class TestLLMClientInit:
    def test_basic_init(self, config):
        from LangCode.services.llm import LLMClient
        client = LLMClient(config)
        assert client.primary_model is not None
        assert client.model_name is not None

    def test_fallback_not_set_by_default(self, config):
        from LangCode.services.llm import LLMClient
        client = LLMClient(config)
        assert client.fallback_model is None

    def test_fallback_set_when_configured(self):
        from LangCode.services.llm import LLMClient
        cfg = Config([{
            **CONFIG_DEFAULTS,
            "model.api_key": "test-key",
            "model.fallback": "gpt-4o",
        }])
        client = LLMClient(cfg)
        assert client.fallback_model is not None


class TestLLMClientFallback:
    def test_switch_to_fallback(self):
        from LangCode.services.llm import LLMClient
        cfg = Config([{
            **CONFIG_DEFAULTS,
            "model.api_key": "test-key",
            "model.fallback": "gpt-4o",
        }])
        client = LLMClient(cfg)
        primary = client.primary_model
        fallback = client.fallback_model
        assert client.switch_to_fallback() is True
        # 交换后 primary 应该是之前的 fallback
        assert client.primary_model is fallback
        assert client.fallback_model is primary

    def test_switch_without_fallback(self, config):
        from LangCode.services.llm import LLMClient
        client = LLMClient(config)
        assert client.switch_to_fallback() is False


class TestStripThinkingSignatures:
    def test_preserves_regular_messages(self, config):
        from LangCode.services.llm import LLMClient
        from langchain_core.messages import HumanMessage, AIMessage
        client = LLMClient(config)
        msgs = [HumanMessage(content="hello"), AIMessage(content="world")]
        result = client.strip_thinking_signatures(msgs)
        assert len(result) == 2
        assert result[0].content == "hello"
        assert result[1].content == "world"

    def test_strips_thinking_blocks(self, config):
        from LangCode.services.llm import LLMClient
        from langchain_core.messages import AIMessage
        client = LLMClient(config)
        msg = AIMessage(content=[
            {"type": "thinking", "thinking": "internal reasoning"},
            {"type": "text", "text": "visible output"},
        ])
        result = client.strip_thinking_signatures([msg])
        assert len(result) == 1
        # thinking 块应被移除，text 块保留
        assert len(result[0].content) == 1
        assert result[0].content[0]["type"] == "text"

    def test_preserves_non_list_content(self, config):
        from LangCode.services.llm import LLMClient
        from langchain_core.messages import AIMessage
        client = LLMClient(config)
        msg = AIMessage(content="simple text")
        result = client.strip_thinking_signatures([msg])
        assert len(result) == 1
        assert result[0].content == "simple text"
