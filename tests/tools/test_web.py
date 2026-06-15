"""tools.builtin.web — fetch_api + web_search 测试"""

import pytest
from unittest.mock import patch, MagicMock

from LangCode.tools.builtin.web import (
    fetch_api, web_search, _search_with_tavily, _search_with_serpapi,
)


class TestFetchAPI:
    @patch("LangCode.tools.builtin.web.httpx.Client")
    def test_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.text = '{"ok": true}'
        mock_resp.status_code = 200
        mock_resp.content = b'{"ok": true}'

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = fetch_api.invoke({"url": "http://example.com/api"})
        assert result.success is True
        assert result.status_code == 200

    @patch("LangCode.tools.builtin.web.httpx.Client")
    def test_failure(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = fetch_api.invoke({"url": "http://invalid.local"})
        assert result.success is False
        assert "connection refused" in result.error


class TestWebSearch:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key(self):
        result = web_search.invoke({"query": "test", "max_results": 5})
        assert result["success"] is False
        assert "API key" in result["error"]

    @patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}, clear=True)
    @patch("LangCode.tools.builtin.web.httpx.post")
    def test_tavily_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "http://example.com", "content": "snippet"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = web_search.invoke({"query": "test query", "max_results": 5})
        assert result["success"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Result 1"

    @patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}, clear=True)
    @patch("LangCode.tools.builtin.web.httpx.post")
    def test_tavily_failure(self, mock_post):
        mock_post.side_effect = Exception("API error")

        result = web_search.invoke({"query": "test", "max_results": 5})
        assert result["success"] is False

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}, clear=True)
    @patch("LangCode.tools.builtin.web.httpx.get")
    def test_serpapi_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "organic_results": [
                {"title": "Result", "link": "http://example.com", "snippet": "info"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = web_search.invoke({"query": "test", "max_results": 5})
        assert result["success"] is True
        assert result["results"][0]["url"] == "http://example.com"


class TestSearchWithTavily:
    @patch("LangCode.tools.builtin.web.httpx.post")
    def test_parses_results(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "T1", "url": "http://a.com", "content": "s1"},
                {"title": "T2", "url": "http://b.com", "content": "s2"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _search_with_tavily("key", "query", 5)
        assert result["success"] is True
        assert len(result["results"]) == 2

    @patch("LangCode.tools.builtin.web.httpx.post")
    def test_empty_results(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _search_with_tavily("key", "query", 5)
        assert result["success"] is True
        assert len(result["results"]) == 0
