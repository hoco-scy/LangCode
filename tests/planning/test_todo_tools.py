"""planning.todo_tools — write_todo / update_todo / modify_todo 工具测试"""

import json
import pytest

from LangCode.planning.todo_tools import (
    create_todo_tools,
    WriteTodoInput, UpdateTodoInput, ModifyTodoInput,
)


class TestTodoToolsCreation:
    def test_creates_three_tools(self):
        tools = create_todo_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"write_todo", "update_todo", "modify_todo"}

    def test_tool_schemas(self):
        tools = create_todo_tools()
        for t in tools:
            assert t.args_schema is not None


class TestWriteTodoTool:
    def test_invocation(self):
        tools = create_todo_tools()
        write_todo = next(t for t in tools if t.name == "write_todo")
        result = write_todo.invoke({"goal": "test goal", "steps": ["step1", "step2"]})
        parsed = json.loads(result)
        assert parsed["goal"] == "test goal"
        assert parsed["total"] == 2
        assert len(parsed["steps"]) == 2


class TestUpdateTodoTool:
    def test_invocation(self):
        tools = create_todo_tools()
        update_todo = next(t for t in tools if t.name == "update_todo")
        result = update_todo.invoke({"step_index": 1, "status": "done", "result": "ok"})
        parsed = json.loads(result)
        assert parsed["step_index"] == 1
        assert parsed["status"] == "done"


class TestModifyTodoTool:
    def test_invocation_add(self):
        tools = create_todo_tools()
        modify_todo = next(t for t in tools if t.name == "modify_todo")
        result = modify_todo.invoke({"add_steps": ["new step"]})
        parsed = json.loads(result)
        assert parsed["add_steps"] == ["new step"]

    def test_invocation_replace(self):
        tools = create_todo_tools()
        modify_todo = next(t for t in tools if t.name == "modify_todo")
        result = modify_todo.invoke({"steps": ["a", "b", "c"]})
        parsed = json.loads(result)
        assert len(parsed["steps"]) == 3


class TestInputSchemas:
    def test_write_todo_input(self):
        inp = WriteTodoInput(goal="test", steps=["a", "b"])
        assert inp.goal == "test"
        assert len(inp.steps) == 2

    def test_write_todo_min_steps(self):
        with pytest.raises(Exception):
            WriteTodoInput(goal="test", steps=["only one"])

    def test_update_todo_defaults(self):
        inp = UpdateTodoInput(step_index=1, status="done")
        assert inp.result == ""

    def test_modify_todo_all_none(self):
        inp = ModifyTodoInput()
        assert inp.steps is None
        assert inp.add_steps is None
        assert inp.remove_indices is None
