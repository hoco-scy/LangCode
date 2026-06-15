"""WebFetchTool + WebSearchTool — 外部数据获取。

fetch_api (WebFetchTool): GET 请求获取 URL 内容
web_search (WebSearchTool): 搜索引擎查询（需要 TAVILY_API_KEY 或 SERPAPI_API_KEY）

WebSearchTool 启动时可选跳过：
  如果未配置 API key，工具仍会注册，但调用时返回提示信息。
"""

import os
import httpx
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.web")


# ============================================================
#  WebFetchTool (fetch_api)
# ============================================================

class FetchAPIInput(BaseModel):
    url: str = Field(description="The URL to fetch data from")


@tool("fetch_api", args_schema=FetchAPIInput)
def fetch_api(url: str):
    """发送 GET 请求获取外部 API 数据，返回响应内容。仅支持 GET，不支持 POST/PUT 等。"""
    from LangCode.shared.models import FetchAPIResponse
    log.info("fetch_api: url=%s", url)
    try:
        with httpx.Client() as client:
            resp = client.get(url)
            log.debug("fetch_api 成功: status=%d size=%d", resp.status_code, len(resp.content))
            return FetchAPIResponse(
                success=True,
                content=resp.text,
                status_code=resp.status_code,
            )
    except Exception as e:
        log.error("fetch_api 失败: %s", e)
        return FetchAPIResponse(success=False, error=str(e))


# ============================================================
#  WebSearchTool (web_search)
# ============================================================

class WebSearchInput(BaseModel):
    query: str = Field(description="搜索查询词")
    max_results: int = Field(default=5, ge=1, le=10, description="最大返回结果数")


@tool("web_search", args_schema=WebSearchInput)
def web_search(query: str, max_results: int = 5):
    """使用搜索引擎搜索互联网信息。返回搜索结果的标题、URL 和摘要。

    需要配置以下环境变量之一：
    - TAVILY_API_KEY: 使用 Tavily 搜索 API（推荐）
    - SERPAPI_API_KEY: 使用 SerpAPI
    """
    log.info("web_search: query=%s max=%d", query, max_results)

    # 优先 Tavily
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        return _search_with_tavily(tavily_key, query, max_results)

    # 备选 SerpAPI
    serpapi_key = os.environ.get("SERPAPI_API_KEY")
    if serpapi_key:
        return _search_with_serpapi(serpapi_key, query, max_results)

    # 无 API key
    log.warning("web_search: 未配置 TAVILY_API_KEY 或 SERPAPI_API_KEY")
    return {
        "success": False,
        "error": "未配置搜索 API key。请设置环境变量 TAVILY_API_KEY 或 SERPAPI_API_KEY。",
        "results": [],
    }


def _search_with_tavily(api_key: str, query: str, max_results: int) -> dict:
    """使用 Tavily Search API 搜索。"""
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:300],
            })

        log.info("tavily 搜索完成: %d 条结果", len(results))
        return {"success": True, "results": results, "total": len(results)}
    except Exception as e:
        log.error("tavily 搜索失败: %s", e)
        return {"success": False, "error": str(e), "results": []}


def _search_with_serpapi(api_key: str, query: str, max_results: int) -> dict:
    """使用 SerpAPI 搜索。"""
    try:
        resp = httpx.get(
            "https://serpapi.com/search",
            params={
                "api_key": api_key,
                "q": query,
                "num": max_results,
                "engine": "google",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "")[:300],
            })

        log.info("serpapi 搜索完成: %d 条结果", len(results))
        return {"success": True, "results": results, "total": len(results)}
    except Exception as e:
        log.error("serpapi 搜索失败: %s", e)
        return {"success": False, "error": str(e), "results": []}
