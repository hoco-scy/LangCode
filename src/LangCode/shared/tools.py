# 工具集：文件读写、Shell/Python 执行、API 请求、Git 操作
import subprocess
import sys
import os
import glob as _glob
import threading
import platform as _platform
import psutil

import httpx
from langchain.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal

from LangCode.shared.logger import get_logger
from LangCode.shared.schemas import (
    ToolResponse, FileContentResponse, WriteResponse, EditResponse,
    SearchResponse, CommandResponse, PythonResponse, FetchAPIResponse,
    GitStatusResponse, GitDiffResponse, GitLogResponse, GitBlameResponse,
    GitCommitInfo, GitBlameEntry,
)

log = get_logger("tools")


class ReadFileInput(BaseModel):
    file_path: str = Field(description="The path to the file to read")
    encode: str = Field(default="utf-8", description="The encoding of the file")


@tool("read_file", args_schema=ReadFileInput)
def read_file(file_path: str, encode: str = "utf-8") -> FileContentResponse:
    """读取文件内容"""
    log.info("read_file: file_path=%s encode=%s", file_path, encode)
    try:
        with open(file_path, mode="r", encoding=encode) as f:
            content = f.read()
            log.debug("read_file 成功: %d 字符", len(content))
            return FileContentResponse(content=content, success=True, file_path=file_path)

    except FileNotFoundError:
        log.warning("read_file 失败: 文件不存在 %s", file_path)
        return FileContentResponse(content="", success=False, error="File not found")
    except UnicodeDecodeError:
        log.warning("read_file 失败: 编码错误 %s", file_path)
        return FileContentResponse(content="", success=False, error="Encoding error")
    except Exception as e:
        log.error("read_file 异常: %s", e)
        return FileContentResponse(content="", success=False, error=str(e))


class FetchAPIInput(BaseModel):
    url: str = Field(description="The URL to fetch data from")


@tool("fetch_api", args_schema=FetchAPIInput)
def fetch_api(url: str) -> FetchAPIResponse:
    """请求外部 API，返回响应内容"""
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


class RunCommandInput(BaseModel):
    command: str = Field(
        description="The shell command to execute, you should ensure the command match the user's OS platform and be safe to run"
    )
    timeout: int = Field(description="The time to wait for a response before giving up. unit: seconds")


@tool("execute_shell", args_schema=RunCommandInput)
def execute_shell(command: str, timeout: int) -> CommandResponse:
    """执行 shell 命令"""
    log.info("execute_shell: command=%s timeout=%ds", command, timeout)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        log.debug("execute_shell 完成: return_code=%d", result.returncode)
        if result.returncode != 0:
            log.warning("execute_shell 非零退出: stderr=%s", result.stderr[:200])
        return CommandResponse(
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else None,
            success=result.returncode == 0,
            return_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        log.warning("execute_shell 超时: %ds", timeout)
        return CommandResponse(output=None, error=f"命令执行超时{timeout}s", success=False)


class RunPythonInput(BaseModel):
    code: str = Field(description="要执行的 Python 代码")
    timeout: int = Field(default=15, ge=1, le=60, description="超时秒数，最长 60 秒")


def _memory_watchdog(proc: subprocess.Popen, limit_mb: int):
    """在独立线程中监控子进程内存，超限直接 kill"""
    limit_bytes = limit_mb * 1024 * 1024
    try:
        ps = psutil.Process(proc.pid)
        while proc.poll() is None:  # 子进程还活着
            try:
                mem = ps.memory_info().rss
                if mem > limit_bytes:
                    log.warning("run_python 内存超限: %dMB > %dMB，强制终止", mem // 1024 // 1024, limit_mb)
                    proc.kill()
                    return
            except psutil.NoSuchProcess:
                return
            threading.Event().wait(0.2)  # 每 200ms 检查一次
    except Exception as e:
        log.warning("watchdog 异常: %s", e)


_SANDBOX_WRAPPER = r"""
import sys

_BLOCKED = {
    "os", "subprocess", "socket", "shutil", "pathlib",
    "ctypes", "importlib", "multiprocessing", "threading",
    "signal", "pty", "fcntl", "termios",
}
_real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

def _safe_import(name, *args, **kwargs):
    top = name.split(".")[0]
    if top in _BLOCKED:
        raise ImportError(f"模块 '{name}' 在沙箱中被禁止使用")
    return _real_import(name, *args, **kwargs)

if isinstance(__builtins__, dict):
    __builtins__["__import__"] = _safe_import
else:
    __builtins__.__import__ = _safe_import

USER_CODE_PLACEHOLDER
"""


@tool("run_python", args_schema=RunPythonInput)
def run_python(code: str, timeout: int = 15) -> PythonResponse:
    """在隔离子进程中执行 Python 代码，跨平台支持 Windows/Unix"""
    code_preview = code[:200].replace("\n", " ")
    log.info("run_python: timeout=%ds code=%s...", timeout, code_preview)

    wrapped = _SANDBOX_WRAPPER.replace("USER_CODE_PLACEHOLDER", code)

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"PYTHONPATH": ""},
        )
    except Exception as e:
        log.error("run_python 启动失败: %s", e)
        return PythonResponse(success=False, output=None, error=f"启动子进程失败：{e}")

    watchdog = threading.Thread(
        target=_memory_watchdog, args=(proc, 256), daemon=True
    )
    watchdog.start()

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        log.warning("run_python 超时: >%ds", timeout)
        return PythonResponse(success=False, output=None,
                              error=f"执行超时（>{timeout}s），进程已强制终止")

    watchdog.join(timeout=1)

    stdout = stdout.strip() or None
    stderr = stderr.strip() or None
    success = proc.returncode == 0

    if success:
        log.debug("run_python 成功: output=%s", (stdout or "")[:200])
        return PythonResponse(success=True, output=stdout, error=None)
    else:
        if proc.returncode == -9 or "MemoryError" in (stderr or ""):
            error = "内存超限（>256MB），进程已强制终止"
        else:
            error = _extract_user_error(stderr)
        log.warning("run_python 失败: error=%s", error)
        return PythonResponse(success=False, output=stdout, error=error)

def _extract_user_error(stderr: str | None) -> str | None:
    """
    子进程的 traceback 包含 wrapper 代码的行号，对 LLM 没有意义。
    找到最后一个真正的异常行返回即可。
    """
    if not stderr:
        return None
    lines = stderr.splitlines()
    # 取最后的异常类型行（通常是 "ExceptionType: message"）
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("File ") and not line.startswith("Traceback"):
            return line
    return stderr


class WriteFileInput(BaseModel):
    file_path: str = Field(description="要写入的文件路径")
    content: str = Field(description="要写入的内容")
    encode: str = Field(default="utf-8", description="文件编码")


@tool("write_file", args_schema=WriteFileInput)
def write_file(file_path: str, content: str, encode: str = "utf-8") -> WriteResponse:
    """写入文件内容，如果文件不存在会自动创建（包括父目录）"""
    log.info("write_file: file_path=%s len=%d", file_path, len(content))
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, mode="w", encoding=encode) as f:
            f.write(content)
        log.debug("write_file 成功: %s", file_path)
        return WriteResponse(success=True, file_path=file_path, bytes_written=len(content.encode(encode)))
    except Exception as e:
        log.error("write_file 失败: %s", e)
        return WriteResponse(success=False, error=str(e))


class EditFileInput(BaseModel):
    file_path: str = Field(description="要编辑的文件路径")
    old_text: str = Field(description="要被替换的原始文本（必须精确匹配文件中的内容）")
    new_text: str = Field(description="替换后的新文本")


@tool("edit_file", args_schema=EditFileInput)
def edit_file(file_path: str, old_text: str, new_text: str) -> EditResponse:
    """精确替换文件中的指定文本。old_text 必须与文件中的内容完全匹配（包括缩进和换行）。"""
    log.info("edit_file: file_path=%s old_len=%d new_len=%d", file_path, len(old_text), len(new_text))
    try:
        with open(file_path, mode="r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_text)
        if count == 0:
            log.warning("edit_file: 未找到匹配文本")
            return EditResponse(success=False, error="未在文件中找到匹配的文本，请检查 old_text 是否精确匹配")
        if count > 1:
            log.warning("edit_file: 匹配到 %d 处，需要唯一匹配", count)
            return EditResponse(success=False, error=f"匹配到 {count} 处相同文本，请提供更精确的上下文使其唯一")

        new_content = content.replace(old_text, new_text, 1)
        with open(file_path, mode="w", encoding="utf-8") as f:
            f.write(new_content)
        log.debug("edit_file 成功: %s", file_path)
        return EditResponse(success=True, file_path=file_path)
    except FileNotFoundError:
        log.warning("edit_file: 文件不存在 %s", file_path)
        return EditResponse(success=False, error=f"文件不存在: {file_path}")
    except Exception as e:
        log.error("edit_file 异常: %s", e)
        return EditResponse(success=False, error=str(e))


class SearchFilesInput(BaseModel):
    pattern: str = Field(description="glob 匹配模式，如 '**/*.py' 或 'src/**/*.json'")
    directory: str = Field(default=".", description="搜索的根目录，默认为当前目录")


@tool("search_files", args_schema=SearchFilesInput)
def search_files(pattern: str, directory: str = ".") -> SearchResponse:
    """使用 glob 模式搜索文件，返回匹配的文件路径列表"""
    log.info("search_files: pattern=%s directory=%s", pattern, directory)
    try:
        full_pattern = os.path.join(directory, pattern)
        matches = _glob.glob(full_pattern, recursive=True)
        matches = [m for m in matches if "__pycache__" not in m and ".git" not in m]
        log.debug("search_files 找到 %d 个文件", len(matches))
        return SearchResponse(success=True, files=matches[:100], total=len(matches))
    except Exception as e:
        log.error("search_files 异常: %s", e)
        return SearchResponse(success=False, error=str(e))


# ============================================================
#  Git 工具
# ============================================================

class GitStatusInput(BaseModel):
    path: Optional[str] = Field(default=None, description="限制显示的目录路径，为空则显示整个仓库状态")


@tool("git_status", args_schema=GitStatusInput)
def git_status(path: Optional[str] = None) -> GitStatusResponse:
    """显示 Git 工作区状态（已修改、已暂存、未跟踪的文件）"""
    log.info("git_status: path=%s", path)
    try:
        cmd = ["git", "status", "--short"]
        if path:
            cmd.append(path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return GitStatusResponse(success=False, error=result.stderr.strip() or "不在 Git 仓库中")
        output = result.stdout.strip()
        return GitStatusResponse(success=True, status=output or "工作区干净，无变更")
    except FileNotFoundError:
        return GitStatusResponse(success=False, error="git 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        return GitStatusResponse(success=False, error="git status 执行超时")


class GitDiffInput(BaseModel):
    file_path: Optional[str] = Field(default=None, description="指定文件路径，为空则显示所有变更")
    staged: bool = Field(default=False, description="True 显示已暂存的变更，False 显示未暂存的变更")


@tool("git_diff", args_schema=GitDiffInput)
def git_diff(file_path: Optional[str] = None, staged: bool = False) -> GitDiffResponse:
    """显示 Git 文件变更差异。可查看未暂存或已暂存的改动。"""
    log.info("git_diff: file_path=%s staged=%s", file_path, staged)
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        if file_path:
            cmd.extend(["--", file_path])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return GitDiffResponse(success=False, error=result.stderr.strip())
        output = result.stdout.strip()
        if not output:
            label = "已暂存" if staged else "未暂存"
            return GitDiffResponse(success=True, diff=f"无{label}变更", lines=0)
        line_count = output.count("\n") + 1
        return GitDiffResponse(success=True, diff=output, lines=line_count)
    except FileNotFoundError:
        return GitDiffResponse(success=False, error="git 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        return GitDiffResponse(success=False, error="git diff 执行超时")


class GitLogInput(BaseModel):
    count: int = Field(default=10, ge=1, le=50, description="显示的提交数量")
    file_path: Optional[str] = Field(default=None, description="限制显示指定文件的提交历史")


@tool("git_log", args_schema=GitLogInput)
def git_log(count: int = 10, file_path: Optional[str] = None) -> GitLogResponse:
    """显示 Git 提交历史。可限制数量和过滤特定文件。"""
    log.info("git_log: count=%d file_path=%s", count, file_path)
    try:
        cmd = ["git", "log", f"-{count}", "--oneline", "--no-decorate"]
        if file_path:
            cmd.extend(["--", file_path])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return GitLogResponse(success=False, error=result.stderr.strip())
        output = result.stdout.strip()
        if not output:
            return GitLogResponse(success=True, commits=[], total=0)
        commits = []
        for line in output.split("\n"):
            parts = line.split(" ", 1)
            if len(parts) == 2:
                commits.append(GitCommitInfo(hash=parts[0], message=parts[1]))
            else:
                commits.append(GitCommitInfo(hash=parts[0], message=""))
        return GitLogResponse(success=True, commits=commits, total=len(commits))
    except FileNotFoundError:
        return GitLogResponse(success=False, error="git 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        return GitLogResponse(success=False, error="git log 执行超时")


class GitBlameInput(BaseModel):
    file_path: str = Field(description="要查看 blame 信息的文件路径")
    start_line: Optional[int] = Field(default=None, ge=1, description="起始行号（从 1 开始）")
    end_line: Optional[int] = Field(default=None, ge=1, description="结束行号（包含）")


@tool("git_blame", args_schema=GitBlameInput)
def git_blame(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> GitBlameResponse:
    """显示文件每一行的最后修改者和提交信息，用于追溯代码变更历史。"""
    log.info("git_blame: file_path=%s lines=%s-%s", file_path, start_line, end_line)
    try:
        cmd = ["git", "blame", "--porcelain"]
        if start_line and end_line:
            cmd.extend(["-L", f"{start_line},{end_line}"])
        elif start_line:
            cmd.extend(["-L", f"{start_line},+20"])
        cmd.append(file_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return GitBlameResponse(success=False, error=result.stderr.strip())
        authors = {}
        current_commit = None
        for line in result.stdout.split("\n"):
            if line.startswith("author "):
                authors.setdefault(current_commit, {})["author"] = line[7:]
            elif line.startswith("summary "):
                authors.setdefault(current_commit, {})["summary"] = line[8:]
            elif len(line) >= 40 and all(c in "0123456789abcdef" for c in line[:40].lower()):
                current_commit = line[:40]
        unique = {}
        for info in authors.values():
            key = f"{info.get('author', '?')}: {info.get('summary', '?')}"
            unique[key] = unique.get(key, 0) + 1
        blame_entries = [GitBlameEntry(reference=k, lines=v) for k, v in sorted(unique.items(), key=lambda x: -x[1])]
        return GitBlameResponse(success=True, file=file_path, blame=blame_entries[:20])
    except FileNotFoundError:
        return GitBlameResponse(success=False, error="git 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        return GitBlameResponse(success=False, error="git blame 执行超时")


all_tools = [read_file, fetch_api, execute_shell, run_python, write_file, edit_file, search_files,
             git_status, git_diff, git_log, git_blame]

if __name__ == "__main__":
    from langchain_core.utils.function_calling import convert_to_openai_tool
    import json

    for t in all_tools:
        print(f"Tool: {t}")
        schema = t.args_schema.model_json_schema()
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        print("---")
