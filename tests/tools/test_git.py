"""tools.builtin.git — Git 工具测试"""

import pytest
from unittest.mock import patch, MagicMock

from LangCode.tools.builtin.git import (
    git_status, git_diff, git_log, git_blame,
    git_tools, _run_git,
    GitStatusInput, GitDiffInput, GitLogInput, GitBlameInput,
)


class TestGitToolsList:
    def test_git_tools_count(self):
        assert len(git_tools) == 4

    def test_git_tools_names(self):
        names = {t.name for t in git_tools}
        assert names == {"git_status", "git_diff", "git_log", "git_blame"}


class TestRunGit:
    @patch("LangCode.tools.builtin.git.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        code, stdout, stderr = _run_git(["status"])
        assert code == 0
        assert stdout == "ok"

    @patch("LangCode.tools.builtin.git.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        code, stdout, stderr = _run_git(["status"])
        assert code == 1
        assert stderr == "error"

    @patch("LangCode.tools.builtin.git.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_installed(self, mock_run):
        code, stdout, stderr = _run_git(["status"])
        assert code == 1
        assert "未安装" in stderr


class TestGitStatus:
    @patch("LangCode.tools.builtin.git._run_git")
    def test_clean_workspace(self, mock_git):
        mock_git.return_value = (0, "", "")
        result = git_status.invoke({"path": "."})
        assert "干净" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_with_changes(self, mock_git):
        mock_git.return_value = (0, " M src/main.py\n?? new_file.py\n", "")
        result = git_status.invoke({"path": "."})
        assert "2 个变更" in result
        assert "src/main.py" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_failure(self, mock_git):
        mock_git.return_value = (1, "", "not a git repo")
        result = git_status.invoke({"path": "."})
        assert "失败" in result


class TestGitDiff:
    @patch("LangCode.tools.builtin.git._run_git")
    def test_no_changes(self, mock_git):
        mock_git.return_value = (0, "", "")
        result = git_diff.invoke({"path": "", "staged": False})
        assert "无变更" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_with_changes(self, mock_git):
        diff_output = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n"
        mock_git.return_value = (0, diff_output, "")
        result = git_diff.invoke({"path": "", "staged": False})
        assert "main.py" in result
        assert "+new" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_staged_diff(self, mock_git):
        mock_git.return_value = (0, "staged changes", "")
        result = git_diff.invoke({"path": "", "staged": True})
        # 验证传了 --staged 参数
        call_args = mock_git.call_args[0][0]
        assert "--staged" in call_args

    @patch("LangCode.tools.builtin.git._run_git")
    def test_long_output_truncated(self, mock_git):
        long_output = "x" * 6000
        mock_git.return_value = (0, long_output, "")
        result = git_diff.invoke({"path": "", "staged": False})
        assert len(result) < 6000
        assert "截断" in result


class TestGitLog:
    @patch("LangCode.tools.builtin.git._run_git")
    def test_with_commits(self, mock_git):
        mock_git.return_value = (0, "abc1234 feat: add feature\ndef5678 fix: bug\n", "")
        result = git_log.invoke({"path": "", "count": 10})
        assert "abc1234" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_no_commits(self, mock_git):
        mock_git.return_value = (0, "", "")
        result = git_log.invoke({"path": "", "count": 10})
        assert "无提交" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_with_path_filter(self, mock_git):
        mock_git.return_value = (0, "abc1234 change\n", "")
        result = git_log.invoke({"path": "src/main.py", "count": 5})
        call_args = mock_git.call_args[0][0]
        assert "src/main.py" in call_args


class TestGitBlame:
    @patch("LangCode.tools.builtin.git._run_git")
    def test_blame_output(self, mock_git):
        porcelain_output = (
            "abc12345deadbeef0123456789abcdef012345678 1 1 1\n"
            "author John Doe\n"
            "author-time 1704067200\n"
            "author-tz +0800\n"
            "committer Jane Smith\n"
            "committer-time 1704067200\n"
            "summary Some commit\n"
            "\tprint('hello')\n"
        )
        mock_git.return_value = (0, porcelain_output, "")
        result = git_blame.invoke({"file_path": "main.py"})
        assert "John Doe" in result or "abc12345" in result

    @patch("LangCode.tools.builtin.git._run_git")
    def test_blame_failure(self, mock_git):
        mock_git.return_value = (1, "", "No such file")
        result = git_blame.invoke({"file_path": "nonexistent.py"})
        assert "失败" in result


class TestInputModels:
    def test_git_status_input_default(self):
        inp = GitStatusInput()
        assert inp.path == "."

    def test_git_diff_input_default(self):
        inp = GitDiffInput()
        assert inp.path == ""
        assert inp.staged is False

    def test_git_log_input_default(self):
        inp = GitLogInput()
        assert inp.count == 10

    def test_git_log_input_validation(self):
        with pytest.raises(Exception):
            GitLogInput(count=0)  # ge=1

    def test_git_blame_input_requires_path(self):
        with pytest.raises(Exception):
            GitBlameInput()  # required field
