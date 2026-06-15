"""PythonTool — 在隔离子进程中执行 Python 代码。"""

import os
import sys
import subprocess
import threading
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.python")


class RunPythonInput(BaseModel):
    code: str = Field(description="要执行的 Python 代码")
    timeout: int = Field(default=15, ge=1, le=60, description="超时秒数，最长 60 秒")


def _memory_watchdog(proc: subprocess.Popen, limit_mb: int):
    """在独立线程中监控子进程内存，超限直接 kill"""
    limit_bytes = limit_mb * 1024 * 1024
    try:
        import psutil
        ps = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                mem = ps.memory_info().rss
                if mem > limit_bytes:
                    log.warning("run_python 内存超限: %dMB > %dMB，强制终止", mem // 1024 // 1024, limit_mb)
                    proc.kill()
                    return
            except psutil.NoSuchProcess:
                return
            threading.Event().wait(0.2)
    except ImportError:
        pass
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
def run_python(code: str, timeout: int = 15):
    """在隔离子进程中执行 Python 代码，跨平台支持 Windows/Unix"""
    from LangCode.shared.models import PythonResponse
    code_preview = code[:200].replace("\n", " ")
    log.info("run_python: timeout=%ds code=%s...", timeout, code_preview)

    wrapped = _SANDBOX_WRAPPER.replace("USER_CODE_PLACEHOLDER", code)

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONPATH": "", "PYTHONUTF8": "1"},
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

    stdout = stdout.strip() if stdout else None
    stderr = stderr.strip() if stderr else None
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


def _extract_user_error(stderr):
    if not stderr:
        return None
    lines = stderr.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("File ") and not line.startswith("Traceback"):
            return line
    return stderr
