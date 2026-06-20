"""agents.router — 路由决策测试（v3: todo 工具）"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from LangCode.agents.router import (
    should_use_tools,
    process_tool_results,
    after_tools_routing,
    _find_last_ai_with_tool_calls,
)
from LangCode.planning.schema import Plan, PlanStep


class TestShouldUseTools:
    def test_with_tool_calls(self):
        state = {"messages": [
            AIMessage(content="test", tool_calls=[{"name": "read_file", "args": {"file_path": "test.py"}, "id": "tc1"}])
        ]}
        assert should_use_tools(state) == "tools"

    def test_without_tool_calls_no_plan(self):
        state = {"messages": [AIMessage(content="done")]}
        assert should_use_tools(state) == "__end__"

    def test_without_tool_calls_active_plan_ends(self):
        """v3: 有活跃计划但无 tool_calls → __end__（不再走 reflector）"""
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        state = {"messages": [AIMessage(content="done")], "current_plan": plan.model_dump()}
        assert should_use_tools(state) == "__end__"

    def test_empty_messages(self):
        assert should_use_tools({"messages": []}) == "__end__"

    def test_pending_delegations_routes_to_router(self):
        """无 tool_calls 但有待处理委派 → router"""
        state = {"messages": [AIMessage(content="done")], "_pending_delegations": [{"route": "explore", "task": "t"}]}
        assert should_use_tools(state) == "router"


class TestProcessToolResults:
    def test_write_todo(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "write_todo",
                "args": {"goal": "重构代码", "steps": ["步骤1", "步骤2", "步骤3"]},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert "current_plan" in updates
        plan = Plan(**updates["current_plan"])
        assert plan.goal == "重构代码"
        assert len(plan.steps) == 3
        # 第一步自动标记为 in_progress
        assert plan.steps[0].status == "in_progress"

    def test_update_todo_done(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
            PlanStep(step_id=2, description="s2"),
        ])
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{
                    "name": "update_todo",
                    "args": {"step_index": 1, "status": "done", "result": "完成"},
                    "id": "tc1",
                }])
            ],
            "current_plan": plan.model_dump(),
        }
        updates = process_tool_results(state)
        updated_plan = Plan(**updates["current_plan"])
        assert updated_plan.steps[0].status == "done"
        assert updated_plan.steps[0].result == "完成"
        # 自动推进到下一步
        assert updated_plan.steps[1].status == "in_progress"

    def test_update_todo_completed(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="done", result="ok"),
        ], current_step=1)
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{
                    "name": "update_todo",
                    "args": {"step_index": 0, "status": "completed"},
                    "id": "tc1",
                }])
            ],
            "current_plan": plan.model_dump(),
        }
        updates = process_tool_results(state)
        updated_plan = Plan(**updates["current_plan"])
        assert updated_plan.status == "completed"

    def test_modify_todo_add_steps(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{
                    "name": "modify_todo",
                    "args": {"add_steps": ["新步骤"]},
                    "id": "tc1",
                }])
            ],
            "current_plan": plan.model_dump(),
        }
        updates = process_tool_results(state)
        updated_plan = Plan(**updates["current_plan"])
        assert len(updated_plan.steps) == 2
        assert updated_plan.steps[1].description == "新步骤"

    def test_delegate_explore(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "delegate_explore",
                "args": {"task": "搜索代码模式"},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert updates["_pending_delegations"] == [{"route": "explore", "task": "搜索代码模式"}]

    def test_no_signal(self):
        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "name": "read_file",
                "args": {"file_path": "test.py"},
                "id": "tc1",
            }])
        ]}
        updates = process_tool_results(state)
        assert updates == {}

    def test_empty_messages(self):
        assert process_tool_results({"messages": []}) == {}


class TestAfterToolsRouting:
    def test_delegate_explore(self):
        state = {"_pending_delegations": [{"route": "explore", "task": "t"}]}
        assert after_tools_routing(state) == "delegated"

    def test_react_default(self):
        state = {}
        assert after_tools_routing(state) == "react"

    def test_plan_does_not_affect_routing(self):
        """v3: 有活跃计划时，路由行为不受影响"""
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        state = {"current_plan": plan.model_dump()}
        assert after_tools_routing(state) == "react"


# ── Bug 暴露测试 ──

class TestProcessedToolIdsBug:
    """Bug: _processed_tool_ids 存储为逗号分隔字符串，但 set() 拆成单字符。

    set("tc1,tc2") → {'t','c','1',',','2'}，不是 {'tc1','tc2'}。
    导致去重完全失效，同一 tool_call 可能被重复消费。
    """

    def test_same_tool_call_not_processed_twice(self):
        """同一个 tool_call 在两轮中不应被重复处理"""
        tc = {"name": "write_todo", "args": {"goal": "test", "steps": ["s1", "s2"]}, "id": "call_abc123"}
        state = {
            "messages": [AIMessage(content="", tool_calls=[tc])],
            "_processed_tool_ids": "",  # 第一轮，未处理过
        }
        updates1 = process_tool_results(state)
        assert "current_plan" in updates1

        # 第二轮：同样的 tool_call，已处理过，应跳过
        state2 = {
            "messages": [AIMessage(content="", tool_calls=[tc])],
            "_processed_tool_ids": updates1.get("_processed_tool_ids", ""),
        }
        updates2 = process_tool_results(state2)
        # 不应再次创建计划
        assert "current_plan" not in updates2

    def test_different_tool_calls_both_processed(self):
        """不同的 tool_call 都应被处理"""
        tc1 = {"name": "write_todo", "args": {"goal": "g1", "steps": ["s1"]}, "id": "id1"}
        tc2 = {"name": "delegate_explore", "args": {"task": "search"}, "id": "id2"}
        state = {
            "messages": [AIMessage(content="", tool_calls=[tc1, tc2])],
            "_processed_tool_ids": "",
        }
        updates = process_tool_results(state)
        assert "current_plan" in updates
        assert "_pending_delegations" in updates


class TestPlanMarkCurrentDoneBug:
    """Bug: mark_current_done 无条件递增 current_step。

    当 current_step 已越界时（step 为 None），仍递增 current_step。
    """

    def test_mark_done_at_last_step_completes_plan(self):
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        plan.mark_current_done("完成")
        assert plan.status == "completed"
        assert plan.current_step == 1

    def test_mark_done_when_already_completed_stays_stable(self):
        """修复后：已完成的计划再次 mark_current_done，current_step 保持稳定"""
        plan = Plan(goal="test", steps=[
            PlanStep(step_id=1, description="s1", status="in_progress"),
        ])
        plan.mark_current_done("完成")
        assert plan.current_step == 1

        plan.mark_current_done("再完成")  # step 为 None，current_step 不再递增
        assert plan.current_step == 1  # 修复后：保持在 1

    def test_mark_done_on_empty_steps_no_crash(self):
        """边界：空 steps 列表不应崩溃"""
        plan = Plan(goal="test", steps=[])
        plan.mark_current_done("完成")  # 不应抛异常
        assert plan.current_step == 0  # 修复后：空列表不递增
