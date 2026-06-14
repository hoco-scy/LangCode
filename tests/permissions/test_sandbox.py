"""permissions.sandbox — PathSandbox 测试"""

import os
import pytest
import tempfile
from pathlib import Path

from LangCode.permissions.sandbox import PathSandbox


@pytest.fixture
def workspace(tmp_path):
    """创建临时工作区"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_x(): pass")
    return str(tmp_path)


@pytest.fixture
def sandbox(workspace):
    return PathSandbox(workspace)


class TestPathSandbox:
    def test_file_in_workspace_allowed(self, sandbox, workspace):
        path = os.path.join(workspace, "src", "main.py")
        assert sandbox.is_path_allowed(path) is True

    def test_file_outside_workspace_denied(self, sandbox):
        assert sandbox.is_path_allowed("/etc/passwd") is False

    def test_workspace_root_allowed(self, sandbox, workspace):
        assert sandbox.is_path_allowed(workspace) is True

    def test_subdirectory_allowed(self, sandbox, workspace):
        assert sandbox.is_path_allowed(os.path.join(workspace, "src")) is True

    def test_parent_directory_denied(self, sandbox, workspace):
        parent = str(Path(workspace).parent)
        assert sandbox.is_path_allowed(parent) is False

    def test_nonexistent_path_in_workspace(self, sandbox, workspace):
        path = os.path.join(workspace, "nonexistent", "file.py")
        # 即使文件不存在，路径在工作区内也应允许
        assert sandbox.is_path_allowed(path) is True

    def test_resolve_safe_path_valid(self, sandbox, workspace):
        path = os.path.join(workspace, "src", "main.py")
        resolved = sandbox.resolve_safe_path(path)
        assert resolved is not None
        assert os.path.isabs(resolved)

    def test_resolve_safe_path_invalid(self, sandbox):
        resolved = sandbox.resolve_safe_path("/etc/passwd")
        assert resolved is None

    def test_validate_file_operation_read_valid(self, sandbox, workspace):
        path = os.path.join(workspace, "src", "main.py")
        is_safe, reason = sandbox.validate_file_operation("read", path)
        assert is_safe is True
        assert reason == ""

    def test_validate_file_operation_outside(self, sandbox):
        is_safe, reason = sandbox.validate_file_operation("write", "/etc/passwd")
        assert is_safe is False
        assert "越界" in reason

    def test_validate_empty_path(self, sandbox):
        is_safe, reason = sandbox.validate_file_operation("read", "")
        assert is_safe is False
        assert "为空" in reason

    def test_validate_delete_workspace_root(self, sandbox, workspace):
        is_safe, reason = sandbox.validate_file_operation("delete", workspace)
        assert is_safe is False
        assert "根目录" in reason

    def test_empty_string_resolves_to_cwd(self):
        sandbox = PathSandbox("")
        # Path("").resolve() → CWD, so sandbox restricts to CWD
        cwd = str(Path.cwd().resolve())
        assert sandbox.is_path_allowed(os.path.join(cwd, "file.py")) is True
        assert sandbox.is_path_allowed("/totally/unrelated/path") is False


class TestAdditionalDirs:
    def test_additional_dir_allowed(self, tmp_path):
        dir1 = tmp_path / "workspace"
        dir1.mkdir()
        dir2 = tmp_path / "other"
        dir2.mkdir()

        sandbox = PathSandbox(str(dir1), additional_dirs=[str(dir2)])
        assert sandbox.is_path_allowed(str(dir2 / "file.py")) is True

    def test_path_not_in_any_dir(self, tmp_path):
        dir1 = tmp_path / "workspace"
        dir1.mkdir()
        dir2 = tmp_path / "other"
        dir2.mkdir()

        sandbox = PathSandbox(str(dir1), additional_dirs=[str(dir2)])
        assert sandbox.is_path_allowed("/tmp/unrelated") is False

    def test_repr(self, workspace):
        sandbox = PathSandbox(workspace)
        r = repr(sandbox)
        assert "PathSandbox" in r
        assert "allowed" in r
