"""BashTool — 执行 shell 命令。

集成 BashClassifier 安全分析：
- 执行前对命令进行语义分类（只读/破坏性/网络）
- 分类结果记录到日志，供权限系统和遥测使用
- 破坏性命令附加警告标记（不阻断，由权限系统决定是否确认）
"""

import subprocess
import locale
import platform as _platform
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger
from LangCode.permissions.classifier import BashClassifier

log = get_logger("tools.shell")

_classifier = BashClassifier()


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
    """执行 shell 命令。自动进行安全分类分析。"""
    from LangCode.shared.models import CommandResponse

    # BashClassifier 安全分析
    classification = _classifier.classify(command)
    safety_tags = []
    if classification.is_destructive:
        safety_tags.append("destructive")
        log.warning("execute_shell [破坏性]: command=%s", command[:200])
    if classification.is_network:
        safety_tags.append("network")
        log.info("execute_shell [网络]: command=%s", command[:200])
    if classification.has_substitution:
        safety_tags.append("substitution")
        log.info("execute_shell [命令替换]: command=%s", command[:200])
    if classification.is_read_only:
        log.debug("execute_shell [只读]: command=%s", command[:200])
    else:
        log.info("execute_shell: command=%s timeout=%ds tags=%s",
                 command[:200], timeout, safety_tags)

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
