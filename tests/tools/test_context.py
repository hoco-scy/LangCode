"""tools.context — ToolUseContext 测试"""

import pytest
from pathlib import Path

from LangCode.tools.context import ToolUseContext


@pytest.fixture
def ctx():
    return ToolUseContext(
        session_id="sess-001",
        agent_id="supervisor",
        workspace_dir="/home/user/project",
        model_name="mimo-v2.5-pro",
    )


class TestToolUseContextDefaults:
    def test_basic_fields(self, ctx):
        assert ctx.session_id == "sess-001"
        assert ctx.agent_id == "supervisor"
        assert ctx.workspace_dir == "/home/user/project"
        assert ctx.model_name == "mimo-v2.5-pro"

    def test_defaults(self, ctx):
        assert ctx.max_output_tokens == 8192
        assert ctx.permission_mode == "default"
        assert ctx.tools == []
        assert ctx.read_file_cache == {}
        assert ctx.write_file_state == set()


class TestCloneForSubagent:
    def test_basic(self, ctx):
        sub = ctx.clone_for_subagent("explore")
        assert sub.agent_id == "explore"
        assert sub.session_id == ctx.session_id
        assert sub.workspace_dir == ctx.workspace_dir
        assert sub.model_name == ctx.model_name

    def test_independent_caches(self, ctx):
        ctx.read_file_cache["/tmp/a.py"] = ("content", 123)
        ctx.write_file_state.add("/tmp/b.py")

        sub = ctx.clone_for_subagent("review")
        assert sub.read_file_cache == {}
        assert sub.write_file_state == set()

    def test_shared_permission_mode(self, ctx):
        ctx.permission_mode = "plan"
        ctx.allowed_dirs = {"/home/user/project"}
        sub = ctx.clone_for_subagent("explore")
        assert sub.permission_mode == "plan"
        assert sub.allowed_dirs == {"/home/user/project"}

    def test_shared_abort_signal(self, ctx):
        import asyncio
        ctx.abort_signal = asyncio.Event()
        sub = ctx.clone_for_subagent("explore")
        assert sub.abort_signal is ctx.abort_signal


class TestRecordWrite:
    def test_records_path(self, ctx):
        ctx.record_write("/home/user/project/file.py")
        assert any("file.py" in p for p in ctx.write_file_state)

    def test_resolve_path(self, ctx):
        ctx.record_write("./relative/path.py")
        assert len(ctx.write_file_state) == 1
        resolved = list(ctx.write_file_state)[0]
        assert Path(resolved).is_absolute()


class TestClearFileCache:
    def test_clear_specific(self, ctx):
        ctx.read_file_cache["/a.py"] = ("content", 1)
        ctx.read_file_cache["/b.py"] = ("content", 2)
        ctx.clear_file_cache("/a.py")
        assert "/a.py" not in ctx.read_file_cache
        assert "/b.py" in ctx.read_file_cache

    def test_clear_all(self, ctx):
        ctx.read_file_cache["/a.py"] = ("content", 1)
        ctx.read_file_cache["/b.py"] = ("content", 2)
        ctx.clear_file_cache()
        assert ctx.read_file_cache == {}
