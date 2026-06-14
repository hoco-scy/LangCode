"""GlobTool — 使用 glob 模式搜索文件。"""

import os
import glob as _glob
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.search")


class SearchFilesInput(BaseModel):
    pattern: str = Field(description="glob 匹配模式，如 '**/*.py' 或 'src/**/*.json'")
    directory: str = Field(default=".", description="搜索的根目录，默认为当前目录")
    max_results: int = Field(default=100, ge=1, le=500, description="最大返回文件数")


@tool("search_files", args_schema=SearchFilesInput)
def search_files(pattern: str, directory: str = ".", max_results: int = 100):
    """使用 glob 模式搜索文件，返回匹配的文件路径列表。自动排除 __pycache__、.git、node_modules、.venv 等目录。"""
    from LangCode.shared.models import SearchResponse
    log.info("search_files: pattern=%s directory=%s max=%d", pattern, directory, max_results)
    try:
        full_pattern = os.path.join(directory, pattern)
        matches = _glob.glob(full_pattern, recursive=True)
        excluded = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".tox", ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
        matches = [
            m for m in matches
            if not any(f"{os.sep}{ex}{os.sep}" in m or m.endswith(f"{os.sep}{ex}") or ex in m.split(os.sep) for ex in excluded)
        ]
        log.debug("search_files 找到 %d 个文件", len(matches))
        return SearchResponse(success=True, files=matches[:max_results], total=len(matches))
    except Exception as e:
        log.error("search_files 异常: %s", e)
        return SearchResponse(success=False, error=str(e))
