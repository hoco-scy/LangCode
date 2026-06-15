"""BashClassifier — 命令语义分析器。

参考 Claude Code bashSecurity.ts 和 readOnlyValidation.ts：
- 识别只读命令（ls, cat, grep, git status...）
- 识别破坏性命令（rm, dd, truncate...）
- 识别网络命令（curl, wget, nc...）
- 解析复合命令（管道、&&、||、;）
- 识别命令替换模式（$(), <()...）

简化实现：不处理完整的引号状态机（Claude Code 的实现有 11 种模式），
而是用正则匹配常见的危险模式。足以覆盖 90% 的场景。
"""

from __future__ import annotations

import re
from typing import Optional
from dataclasses import dataclass

from LangCode.shared.logger import get_logger

log = get_logger("permissions.classifier")


# ── 命令分类集合 ──

# 只读命令（不产生副作用）
READ_ONLY_COMMANDS: frozenset[str] = frozenset({
    "ls", "ll", "la", "dir",
    "cat", "head", "tail", "less", "more",
    "grep", "egrep", "fgrep", "rg", "ag", "ack",
    "find", "fd", "locate", "which", "whereis", "type",
    "wc", "stat", "file", "du", "df",
    "echo", "printf", "date", "cal",
    "pwd", "env", "printenv", "uname", "whoami", "id", "hostname",
    "jq", "awk", "cut", "sort", "uniq", "tr", "sed",  # sed 只用于输出时
    "diff", "cmp", "comm",
    "git", "hg", "svn", "bzr",
    "tree", "md5sum", "sha256sum",
})

# 破坏性命令（删除、覆盖、格式化）
DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset({
    "rm", "rmdir", "unlink",
    "mv", "rename",
    "cp",  # 覆盖时破坏性
    "dd", "shred", "truncate",
    "mkfs", "format", "fdisk", "parted",
    "chmod", "chown", "chgrp",
    "kill", "killall", "pkill", "xkill",
    "shutdown", "reboot", "halt", "poweroff",
    "mkswap", "swapon", "swapoff",
})

# 网络命令
NETWORK_COMMANDS: frozenset[str] = frozenset({
    "curl", "wget", "httpie", "http",
    "nc", "netcat", "ncat", "socat",
    "ssh", "scp", "sftp", "rsync",  # rsync 本地操作不是网络
    "telnet", "ftp", "sftp",
    "dig", "nslookup", "host", "ping", "traceroute",
})

# 包管理器（安装/更新/删除）
PACKAGE_MANAGERS: frozenset[str] = frozenset({
    "pip", "pip3", "conda", "apt", "apt-get", "yum", "dnf", "brew",
    "npm", "yarn", "pnpm", "cargo", "go", "gem", "composer",
})

# 命令替换模式（参考 Claude Code COMMAND_SUBSTITUTION_PATTERNS）
SUBSTITUTION_PATTERNS: list[tuple[str, str]] = [
    (r"<\(", "process substitution <()"),
    (r">\(", "process substitution >()"),
    (r"\$\(", "$() command substitution"),
    (r"\$\{", "${} parameter expansion"),
    (r"\$\[", "$[] legacy arithmetic"),
]


@dataclass
class CommandClassification:
    """命令分类结果"""
    is_read_only: bool = True
    is_destructive: bool = False
    is_network: bool = False
    is_package_manager: bool = False
    has_substitution: bool = False
    primary_command: str = ""       # 主命令名（第一个非重定向词）
    command_chain: list[str] = None # 复合命令中的各个命令

    def __post_init__(self):
        if self.command_chain is None:
            self.command_chain = []


class BashClassifier:
    """命令语义分析器。

    用法：
        classifier = BashClassifier()
        result = classifier.classify("rm -rf /tmp/test")
        assert result.is_destructive is True
        assert result.is_read_only is False
    """

    def classify(self, command: str) -> CommandClassification:
        """分析命令的语义分类。

        Args:
            command: Shell 命令字符串

        Returns:
            CommandClassification 包含分类结果
        """
        cmd = command.strip()
        if not cmd:
            return CommandClassification()

        result = CommandClassification()

        # 检查命令替换
        result.has_substitution = self._has_substitution(cmd)

        # 解析复合命令
        commands = self._parse_command_chain(cmd)
        result.command_chain = commands

        if commands:
            result.primary_command = self._extract_command_name(commands[0])

        # 对每个子命令分析
        for sub_cmd in commands:
            cmd_name = self._extract_command_name(sub_cmd)

            if cmd_name in DESTRUCTIVE_COMMANDS:
                result.is_destructive = True
                result.is_read_only = False

            if cmd_name in NETWORK_COMMANDS:
                result.is_network = True

            if cmd_name in PACKAGE_MANAGERS:
                result.is_package_manager = True
                # 安装/更新操作视为破坏性
                if any(kw in sub_cmd for kw in ["install", "remove", "uninstall",
                                                   "purge", "upgrade", "update"]):
                    result.is_destructive = True
                    result.is_read_only = False

            if cmd_name in READ_ONLY_COMMANDS:
                pass  # 不影响 is_read_only（默认 True）
            elif cmd_name not in READ_ONLY_COMMANDS:
                result.is_read_only = False

        # 如果所有子命令都是只读的，标记为只读
        if not result.is_destructive and not result.is_network:
            all_read = all(
                self._extract_command_name(c) in READ_ONLY_COMMANDS
                for c in commands
            )
            result.is_read_only = all_read

        return result

    def _extract_command_name(self, cmd: str) -> str:
        """从可能包含路径、选项和参数的命令字符串中提取命令名。

        例如: "/usr/bin/python3 -c 'print(1)'" → "python3"
              "sudo rm -rf /tmp" → "sudo"
        """
        parts = cmd.strip().split()
        if not parts:
            return ""

        cmd_name = parts[0]

        # 跳过 sudo
        if cmd_name == "sudo" and len(parts) > 1:
            cmd_name = parts[1]

        # 去掉路径前缀
        if "/" in cmd_name:
            cmd_name = cmd_name.rsplit("/", 1)[-1]

        return cmd_name

    def _parse_command_chain(self, command: str) -> list[str]:
        """解析复合命令，拆分为各个子命令。

        分隔符: |, &&, ||, ;
        注意：不处理括号分组（太复杂）
        """
        # 简单拆分（不处理引号内的分隔符）
        commands: list[str] = []
        current = ""
        in_single_quote = False
        in_double_quote = False
        i = 0

        while i < len(command):
            char = command[i]

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current += char
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current += char
            elif not in_single_quote and not in_double_quote:
                if char == "|":
                    if current.strip():
                        commands.append(current.strip())
                    current = ""
                    if i + 1 < len(command) and command[i + 1] == "|":
                        i += 1  # 跳过 ||
                elif char == "&":
                    if current.strip():
                        commands.append(current.strip())
                    current = ""
                    if i + 1 < len(command) and command[i + 1] == "&":
                        i += 1  # 跳过 &&
                elif char == ";":
                    if current.strip():
                        commands.append(current.strip())
                    current = ""
                else:
                    current += char
            else:
                current += char
            i += 1

        if current.strip():
            commands.append(current.strip())

        return commands

    def _has_substitution(self, command: str) -> bool:
        """检查命令中是否包含命令替换模式。"""
        for pattern, _ in SUBSTITUTION_PATTERNS:
            if re.search(pattern, command):
                return True
        return False
