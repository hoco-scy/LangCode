"""ShellTool — 执行 shell 命令。

集成 BashClassifier 安全分析：
- 执行前对命令进行语义分类（只读/破坏性/网络）
- 分类结果记录到日志，供权限系统和遥测使用
- 破坏性命令附加警告标记（不阻断，由权限系统决定是否确认）

跨平台支持：
- macOS/Linux: 原生 bash
- Windows: 通过 LC_BASH_PATH 环境变量或 shell.bash_path 配置项
  指定 git-bash.exe 路径以启用 bash 语法。留空则默认 cmd.exe。
"""

import subprocess
import locale
import os
import platform as _platform
from pathlib import Path
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger
from LangCode.permissions.classifier import BashClassifier

log = get_logger("tools.shell")

_classifier = BashClassifier()


def _detect_shell() -> str | None:
    """检测可用的 bash 路径。

    优先级：
    1. 环境变量 LC_BASH_PATH
    2. 配置文件 shell.bash_path
    3. 常见安装路径（git-bash.exe）
    4. Windows 无 bash → None（走 cmd.exe）
    """
    # 环境变量
    env_path = os.getenv("LC_BASH_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path

    # 配置文件
    try:
        from LangCode.services.config import Config
        config = Config.load()
        bash_path = config.get("shell.bash_path", "")
        if bash_path and Path(bash_path).exists():
            return bash_path
    except Exception:
        pass

    # 常见路径探测
    if _platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
        ]
        for p in candidates:
            if Path(p).exists():
                return p
        return None  # Windows 无 bash → cmd.exe

    # 非 Windows
    for p in ["/bin/bash", "/usr/bin/bash"]:
        if Path(p).exists():
            return p
    return None


def _get_shell_encoding() -> str:
    """返回 shell 子进程的正确编码：Windows cmd.exe 用系统代码页，其他用 UTF-8"""
    if _DETECTED_SHELL is None and _platform.system() == "Windows":
        return locale.getpreferredencoding(False)
    return "utf-8"


_DETECTED_SHELL: str | None = None


def get_shell() -> str | None:
    """获取（缓存的）bash 路径。None 表示用默认 shell。"""
    global _DETECTED_SHELL
    if _DETECTED_SHELL is None:
        _DETECTED_SHELL = _detect_shell()
        if _DETECTED_SHELL:
            log.info("检测到 bash: %s", _DETECTED_SHELL)
        else:
            log.info("未检测到 bash，使用系统默认 shell")
    return _DETECTED_SHELL


def _build_command(command: str) -> str:
    """将原始命令包装为 bash 可执行形式。

    当检测到 bash 时，用 '<command>' 通过 stdin 传递给 bash 以避免引号转义问题。
    """
    shell = get_shell()
    if shell:
        return f'"{shell}" -c "{command}"'
    return command


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
        final_command = _build_command(command)
        result = subprocess.run(
            final_command,
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
