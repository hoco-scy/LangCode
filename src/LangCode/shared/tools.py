# 目前实现文件读取、阅读网站、shell执行、Python运行 四个基础工具
import subprocess
import sys

import httpx
from langchain.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal


class ReadFileInput(BaseModel):
    file_path: str = Field(description="The path to the file to read")
    encode: str = Field(description="The encoding of the file")


@tool("read_file", args_schema=ReadFileInput)
def read_file(file_path: str, encode: str = "utf-8") -> dict:
    """读取文件内容"""
    try:
        with open(file_path, mode="r", encoding=encode) as f:
            content = f.read()
            return {"content": content, "success": True}

    except FileNotFoundError:
        return {"content": "", "success": False, "error": "File not found"}
    except UnicodeDecodeError:
        return {"content": "", "success": False, "error": "Encoding error"}
    except Exception as e:
        return {"content": "", "success": False, "error": e}


class FetchAPIInput(BaseModel):
    url: str = Field(description="The URL to fetch data from")


@tool("fetch_api", args_schema=FetchAPIInput)
async def fetch_api(url: str) -> dict:
    """异步请求外部 API"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            return {"content": resp.content, "success": True}

    except Exception as e:
        return {"content": "", "success": False, "error": e}


class RunCommandInput(BaseModel):
    command: str = Field(
        description="The shell command to execute, you should ensure the command match the user's OS platform and be safe to run"
    )
    timeout: int = Field(description="The time to wait for a response before giving up. unit: seconds")


@tool("execute_shell", args_schema=RunCommandInput)
def execute_shell(command: str, timeout: int) -> dict:
    """执行 shell 命令"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout  # 防止命令挂死
        )
        return {
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
            "success": result.returncode == 0,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"output": None, "error": f"命令执行超时{timeout}s", "success": False}


class RunPythonInput(BaseModel):
    code: str = Field(description="要执行的 Python 代码")
    timeout: int = Field(default=15, ge=1, le=60, description="超时秒数，最长 60 秒")


# 注入到子进程的沙箱 wrapper，限制资源并屏蔽危险模块
_SANDBOX_WRAPPER = r"""
import sys
import resource

# ---------- 资源限制 ----------
# 内存上限 256 MB
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
# 禁止创建新子进程
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

# ---------- 模块黑名单 ----------
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

# ---------- 执行用户代码 ----------
USER_CODE_PLACEHOLDER
"""


@tool("run_python", args_schema=RunPythonInput)
def run_python(code: str, timeout: int = 15) -> dict:
    """
    在隔离的子进程中执行 Python 代码。
    - 超时强制终止，不影响主进程
    - 内存限制 256 MB
    - 禁止访问 os / subprocess / socket 等危险模块
    - 禁止创建新子进程或线程
    返回 stdout 输出、stderr、是否成功。
    """
    wrapped = _SANDBOX_WRAPPER.replace("USER_CODE_PLACEHOLDER", code)

    try:
        result = subprocess.run(
            [sys.executable, "-c", wrapped],
            capture_output=True,
            text=True,
            timeout=timeout,
            # 不继承父进程环境变量，减少信息泄露
            env={"PYTHONPATH": ""},
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": None,
            "error": f"执行超时（>{timeout}s），进程已强制终止",
        }
    except Exception as e:
        return {
            "success": False,
            "output": None,
            "error": f"启动子进程失败：{e}",
        }

    stdout = result.stdout.strip() or None
    stderr = result.stderr.strip() or None
    success = result.returncode == 0

    if success:
        return {
            "success": True,
            "output": stdout,
            "error": None,
        }
    else:
        # 过滤掉 wrapper 内部的堆栈帧，只暴露用户代码的错误
        user_error = _extract_user_error(stderr)
        return {
            "success": False,
            "output": stdout,  # 出错前可能已有部分输出
            "error": user_error,
        }


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
