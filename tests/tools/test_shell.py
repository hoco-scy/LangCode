"""tools.builtin.shell — execute_shell 测试（含 BashClassifier 集成）"""

import pytest
from unittest.mock import patch, MagicMock

from LangCode.tools.builtin.shell import execute_shell


class TestExecuteShell:
    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello", stderr="",
        )
        result = execute_shell.invoke({"command": "echo hello", "timeout": 30})
        assert result.success is True
        assert result.output == "hello"

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="not found",
        )
        result = execute_shell.invoke({"command": "bad_command", "timeout": 30})
        assert result.success is False
        assert result.error == "not found"

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        result = execute_shell.invoke({"command": "sleep 100", "timeout": 5})
        assert result.success is False
        assert "超时" in result.error

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_read_only_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="file.py", stderr="")
        result = execute_shell.invoke({"command": "ls -la", "timeout": 30})
        assert result.success is True

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_destructive_command_still_executes(self, mock_run):
        """BashClassifier 记录日志但不阻断执行"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = execute_shell.invoke({"command": "rm /tmp/test", "timeout": 30})
        assert result.success is True

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_network_command_still_executes(self, mock_run):
        """BashClassifier 记录日志但不阻断执行"""
        mock_run.return_value = MagicMock(returncode=0, stdout="response", stderr="")
        result = execute_shell.invoke({"command": "curl http://example.com", "timeout": 30})
        assert result.success is True

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_stderr_only_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="warning")
        result = execute_shell.invoke({"command": "echo ok", "timeout": 30})
        assert result.success is True
        assert result.error is None  # returncode=0 时不返回 stderr

    @patch("LangCode.tools.builtin.shell.subprocess.run")
    def test_stderr_returned_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        result = execute_shell.invoke({"command": "false", "timeout": 30})
        assert result.success is False
        assert result.error == "error msg"


class TestShellInputSchema:
    def test_default_timeout(self):
        from LangCode.tools.builtin.shell import RunCommandInput
        inp = RunCommandInput(command="ls")
        assert inp.timeout == 30

    def test_timeout_validation(self):
        from LangCode.tools.builtin.shell import RunCommandInput
        with pytest.raises(Exception):
            RunCommandInput(command="ls", timeout=0)  # ge=1
        with pytest.raises(Exception):
            RunCommandInput(command="ls", timeout=301)  # le=300
