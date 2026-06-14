"""WebFetchTool — 发送 GET 请求获取外部 API 数据。"""

import httpx
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.web")


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
