"""tools.builtin.git — Git 操作工具集。

提供 git status, git diff, git log, git blame 四个只读 Git 工具。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.tools import tool

from LangCode.shared.logger import get_logger

log = get_logger("tools.builtin.git")


# ── 输入模型 ──

class GitStatusInput(BaseModel):
    """git status 输入"""
    path: str = Field(default=".", description="要检查的目录路径")


class GitDiffInput(BaseModel):
    """git diff 输入"""
    path: str = Field(default="", description="要 diff 的文件路径（空则全部）")
    staged: bool = Field(default=False, description="是否查看暂存区 diff")


class GitLogInput(BaseModel):
    """git log 输入"""
    path: str = Field(default="", description="限定文件路径")
    count: int = Field(default=10, description="显示条数", ge=1, le=50)


class GitBlameInput(BaseModel):
    """git blame 输入"""
    file_path: str = Field(description="要 blame 的文件路径")


# ── 工具实现 ──

def _run_git(args: list[str], cwd: str = ".") -> tuple[int, str, str]:
    """执行 git 命令。"""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", "git 未安装"
    except subprocess.TimeoutExpired:
        return 1, "", "git 命令超时"


@tool("git_status", args_schema=GitStatusInput)
def git_status(path: str = ".") -> str:
    """查看 Git 工作区状态（新增/修改/删除的文件）。"""
    code, stdout, stderr = _run_git(["status", "--porcelain"], cwd=path)
    if code != 0:
        return f"[git status 失败] {stderr}"
    if not stdout.strip():
        return "工作区干净，无变更文件。"
    lines = stdout.strip().splitlines()
    summary = f"共 {len(lines)} 个变更文件：\n"
    for line in lines[:30]:
        summary += f"  {line}\n"
    if len(lines) > 30:
        summary += f"  ... 还有 {len(lines) - 30} 个文件\n"
    return summary


@tool("git_diff", args_schema=GitDiffInput)
def git_diff(path: str = "", staged: bool = False) -> str:
    """查看 Git diff（工作区或暂存区的变更）。"""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args.extend(["--", path])
    code, stdout, stderr = _run_git(args)
    if code != 0:
        return f"[git diff 失败] {stderr}"
    if not stdout.strip():
        return "无变更。"
    # 限制输出长度
    if len(stdout) > 5000:
        return stdout[:5000] + f"\n\n[... 输出截断，共 {len(stdout)} 字符]"
    return stdout


@tool("git_log", args_schema=GitLogInput)
def git_log(path: str = "", count: int = 10) -> str:
    """查看 Git 提交日志。"""
    args = ["log", f"--oneline", f"-{count}"]
    if path:
        args.extend(["--", path])
    code, stdout, stderr = _run_git(args)
    if code != 0:
        return f"[git log 失败] {stderr}"
    if not stdout.strip():
        return "无提交记录。"
    return stdout


@tool("git_blame", args_schema=GitBlameInput)
def git_blame(file_path: str) -> str:
    """查看文件的逐行 blame 信息（谁修改了哪一行）。"""
    code, stdout, stderr = _run_git(["blame", "--porcelain", file_path])
    if code != 0:
        return f"[git blame 失败] {stderr}"
    # 简化输出：只保留 commit + author + line
    lines = stdout.splitlines()
    result_lines = []
    current_commit = ""
    current_author = ""
    for line in lines:
        if line.startswith("author "):
            current_author = line[7:]
        elif line.startswith("summary "):
            pass
        elif not line.startswith("\t") and len(line) >= 40:
            current_commit = line[:8]
        elif line.startswith("\t"):
            result_lines.append(f"{current_commit} {current_author}: {line[1:]}")
    if len(result_lines) > 50:
        result_lines = result_lines[:50]
        result_lines.append(f"[... 共 {len(stdout.splitlines())} 行，仅显示前 50 行]")
    return "\n".join(result_lines) if result_lines else "无法解析 blame 信息。"


# ── 导出 ──
git_tools = [git_status, git_diff, git_log, git_blame]
