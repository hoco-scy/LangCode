"""GlobTool + GrepTool — 文件搜索和内容搜索。

GlobTool (search_files): 使用 glob 模式搜索文件路径
GrepTool (grep_content): 使用正则表达式搜索文件内容（优先 ripgrep，fallback Python re）
"""

import os
import glob as _glob
import subprocess
import shutil
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.search")

# 常见排除目录
_EXCLUDED_DIRS = frozenset({
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".tox", ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "dist", "build", ".langcode",
})


def _should_exclude(path: str) -> bool:
    """检查路径是否应被排除。"""
    parts = path.replace("\\", "/").split("/")
    return any(p in _EXCLUDED_DIRS for p in parts)


# ============================================================
#  GlobTool (search_files)
# ============================================================

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
        matches = [m for m in matches if not _should_exclude(m)]
        log.debug("search_files 找到 %d 个文件", len(matches))
        return SearchResponse(success=True, files=matches[:max_results], total=len(matches))
    except Exception as e:
        log.error("search_files 异常: %s", e)
        return SearchResponse(success=False, error=str(e))


# ============================================================
#  GrepTool (grep_content)
# ============================================================

class GrepContentInput(BaseModel):
    pattern: str = Field(description="正则表达式搜索模式（支持 ripgrep regex 语法）")
    directory: str = Field(default=".", description="搜索的根目录，默认为当前目录")
    glob_filter: str = Field(default="", description="文件过滤 glob 模式，如 '*.py' 或 '*.ts'。留空则搜索所有文本文件")
    max_results: int = Field(default=50, ge=1, le=200, description="最大返回匹配行数")
    context_lines: int = Field(default=0, ge=0, le=5, description="每个匹配显示的上下文行数")


@tool("grep_content", args_schema=GrepContentInput)
def grep_content(
    pattern: str,
    directory: str = ".",
    glob_filter: str = "",
    max_results: int = 50,
    context_lines: int = 0,
):
    """使用正则表达式搜索文件内容。优先使用 ripgrep（rg），若不可用则 fallback 到 Python re。

    返回匹配的文件路径、行号和内容。自动排除 __pycache__、.git、node_modules 等目录。
    """
    log.info("grep_content: pattern=%s dir=%s glob=%s max=%d",
             pattern, directory, glob_filter, max_results)

    # 优先使用 ripgrep
    rg_path = shutil.which("rg")
    if rg_path:
        return _grep_with_rg(rg_path, pattern, directory, glob_filter, max_results, context_lines)

    # fallback: Python re
    return _grep_with_python(pattern, directory, glob_filter, max_results, context_lines)


def _grep_with_rg(
    rg_path: str,
    pattern: str,
    directory: str,
    glob_filter: str,
    max_results: int,
    context_lines: int,
):
    """使用 ripgrep 搜索。"""
    from LangCode.shared.models import SearchResponse

    cmd = [rg_path, "--no-heading", "--line-number", "--color=never"]

    if context_lines > 0:
        cmd.extend(["--context", str(context_lines)])

    # 排除常见目录
    for d in _EXCLUDED_DIRS:
        cmd.extend(["--glob", f"!{d}"])

    if glob_filter:
        cmd.extend(["--glob", glob_filter])

    cmd.extend(["--max-count", str(max_results)])
    cmd.append(pattern)
    cmd.append(directory)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        output = result.stdout.strip()

        if not output:
            return SearchResponse(success=True, files=[], total=0)

        # 解析 ripgrep 输出: file:line:content
        matches = []
        for line in output.splitlines()[:max_results]:
            matches.append(line)

        # 提取涉及的文件列表
        files = []
        seen = set()
        for m in matches:
            parts = m.split(":", 2)
            if parts[0] and parts[0] not in seen:
                seen.add(parts[0])
                files.append(parts[0])

        return SearchResponse(
            success=True,
            files=files,
            total=len(matches),
            error=output[:2000] if len(matches) > 0 else None,
        )
    except subprocess.TimeoutExpired:
        return SearchResponse(success=False, error="ripgrep 搜索超时(30s)")
    except Exception as e:
        log.error("ripgrep 异常: %s", e)
        return SearchResponse(success=False, error=str(e))


def _grep_with_python(
    pattern: str,
    directory: str,
    glob_filter: str,
    max_results: int,
    context_lines: int,
):
    """使用 Python re 搜索（ripgrep 不可用时的 fallback）。"""
    import re
    from LangCode.shared.models import SearchResponse

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return SearchResponse(success=False, error=f"无效的正则表达式: {e}")

    file_pattern = glob_filter or "**/*"
    all_files = _glob.glob(os.path.join(directory, file_pattern), recursive=True)
    all_files = [f for f in all_files if not _should_exclude(f) and os.path.isfile(f)]

    matches = []
    files_seen = set()

    for fpath in all_files:
        if len(matches) >= max_results:
            break
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            if regex.search(line):
                match_entry = f"{fpath}:{i+1}:{line.rstrip()}"
                matches.append(match_entry)
                files_seen.add(fpath)

                if len(matches) >= max_results:
                    break

    return SearchResponse(
        success=True,
        files=list(files_seen),
        total=len(matches),
        error="\n".join(matches[:max_results]) if matches else None,
    )
