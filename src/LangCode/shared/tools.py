# 目前实现文件读取、阅读网站、shell执行、Python运行 四个基础工具
import subprocess
import sys

import httpx
from langchain.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal

from LangCode.shared.logger import get_logger

log = get_logger("tools")


class ReadFileInput(BaseModel):
    file_path: str = Field(description="The path to the file to read")
    encode: str = Field(description="The encoding of the file")


@tool("read_file", args_schema=ReadFileInput)
def read_file(file_path: str, encode: str = "utf-8") -> dict:
    """读取文件内容"""
    log.info("read_file: file_path=%s encode=%s", file_path, encode)
    try:
        with open(file_path, mode="r", encoding=encode) as f:
            content = f.read()
            log.debug("read_file 成功: %d 字符", len(content))
            return {"content": content, "success": True}

    except FileNotFoundError:
        log.warning("read_file 失败: 文件不存在 %s", file_path)
        return {"content": "", "success": False, "error": "File not found"}
    except UnicodeDecodeError:
        log.warning("read_file 失败: 编码错误 %s", file_path)
        return {"content": "", "success": False, "error": "Encoding error"}
    except Exception as e:
        log.error("read_file 异常: %s", e)
        return {"content": "", "success": False, "error": e}


class FetchAPIInput(BaseModel):
    url: str = Field(description="The URL to fetch data from")


@tool("fetch_api", args_schema=FetchAPIInput)
def fetch_api(url: str) -> dict:
    """请求外部 API"""
    log.info("fetch_api: url=%s", url)
    try:
        with httpx.Client() as client:
            resp = client.get(url)
            log.debug("fetch_api 成功: status=%d size=%d", resp.status_code, len(resp.content))
            return {"content": resp.content.decode(), "success": True}
    except Exception as e:
        log.error("fetch_api 失败: %s", e)
        return {"content": "", "success": False, "error": str(e)}


class RunCommandInput(BaseModel):
    command: str = Field(
        description="The shell command to execute, you should ensure the command match the user's OS platform and be safe to run"
    )
    timeout: int = Field(description="The time to wait for a response before giving up. unit: seconds")


@tool("execute_shell", args_schema=RunCommandInput)
def execute_shell(command: str, timeout: int) -> dict:
    """执行 shell 命令"""
    log.info("execute_shell: command=%s timeout=%ds", command, timeout)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout  # 防止命令挂死
        )
        log.debug("execute_shell 完成: return_code=%d", result.returncode)
        if result.returncode != 0:
            log.warning("execute_shell 非零退出: stderr=%s", result.stderr[:200])
        return {
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
            "success": result.returncode == 0,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        log.warning("execute_shell 超时: %ds", timeout)
        return {"output": None, "error": f"命令执行超时{timeout}s", "success": False}


class RunPythonInput(BaseModel):
    code: str = Field(description="要执行的 Python 代码")
    timeout: int = Field(default=15, ge=1, le=60, description="超时秒数，最长 60 秒")


import sys
import subprocess
import platform
import threading
import psutil

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
def run_python(code: str, timeout: int = 15) -> dict:
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
        return {"success": False, "output": None, "error": f"启动子进程失败：{e}"}

    # 启动内存监控线程（跨平台）
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
        return {"success": False, "output": None,
                "error": f"执行超时（>{timeout}s），进程已强制终止"}

    watchdog.join(timeout=1)

    stdout = stdout.strip() or None
    stderr = stderr.strip() or None
    success = proc.returncode == 0

    if success:
        log.debug("run_python 成功: output=%s", (stdout or "")[:200])
        return {"success": True, "output": stdout, "error": None}
    else:
        # 区分内存超限 vs 普通错误
        if proc.returncode == -9 or "MemoryError" in (stderr or ""):
            error = "内存超限（>256MB），进程已强制终止"
        else:
            error = _extract_user_error(stderr)
        log.warning("run_python 失败: error=%s", error)
        return {"success": False, "output": stdout, "error": error}

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


all_tools = [read_file, fetch_api, execute_shell, run_python]

if __name__ == "__main__":
    from langchain_core.utils.function_calling import convert_to_openai_tool
    import json

    for t in all_tools:
        print(f"Tool: {t}")
        schema = t.args_schema.model_json_schema()
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        print("---")
