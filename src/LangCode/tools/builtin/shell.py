"""BashTool — 执行 shell 命令。"""

import subprocess
import locale
import platform as _platform
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.shell")


def _get_shell_encoding() -> str:
    """返回 shell 子进程的正确编码：Windows 用系统代码页，其他平台用 UTF-8"""
    if _platform.system() == "Windows":
        return locale.getpreferredencoding(False)
    return "utf-8"


class RunCommandInput(BaseModel):
    command: str = Field(
        description="The shell command to execute, you should ensure the command match the user's OS platform and be safe to run"
    )
    timeout: int = Field(default=30, ge=1, le=300, description="超时秒数，默认 30，最长 300")


@tool("execute_shell", args_schema=RunCommandInput)
def execute_shell(command: str, timeout: int = 30):
    """执行 shell 命令"""
    from LangCode.shared.models import CommandResponse
    log.info("execute_shell: command=%s timeout=%ds", command, timeout)
    try:
        enc = _get_shell_encoding()
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding=enc,
            errors="replace",
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
