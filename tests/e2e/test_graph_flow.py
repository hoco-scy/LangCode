"""E2E 集成测试 — 测试完整图流程，Mock LLM 调用。

覆盖场景：
1. 简单 ReAct 循环（agent → tools → auto_verify → router → agent → END）
2. 计划创建 + 执行（write_todo → update_todo → completed）
3. auto_verify 失败修复循环
4. 委派 Explore 子图
"""

import os
import pytest
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from LangCode.agents.graph_builder import (
    build_supervisor_graph,
    build_explore_subgraph,
)


# ── 辅助工具 ──


class SequenceFakeLLM(BaseChatModel):
    """按顺序返回预定义 AIMessage 的 Fake LLM。

    支持 bind_tools（no-op），适用于 LangGraph 图流程测试。
    """

    responses: List[AIMessage]
    _index: int = 0

    @property
    def _llm_type(self) -> str:
        return "sequence-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self._index >= len(self.responses):
            raise IndexError(
                f"SequenceFakeLLM: 预定义响应用完 (共 {len(self.responses)} 个)"
            )
        resp = self.responses[self._index]
        self._index += 1
        return ChatResult(generations=[ChatGeneration(message=resp)])

    @property
    def _identifying_params(self) -> dict:
        return {"num_responses": len(self.responses)}


def make_tool_call_msg(tool_calls: list[dict]) -> AIMessage:
    """创建带 tool_calls 的 AIMessage"""
    return AIMessage(content="", tool_calls=tool_calls)


def make_text_msg(content: str) -> AIMessage:
    """创建纯文本 AIMessage（无 tool_calls）"""
    return AIMessage(content=content)


def make_initial_state(user_msg: str = "请帮我分析代码") -> dict:
    """创建初始图状态"""
    return {
        "messages": [HumanMessage(content=user_msg)],
        "route": "",
        "current_plan": None,
        "task_description": "",
        "verify_errors": None,
        "memory_context": "",
        "supervisor_iterations": 0,
        "_processed_tool_ids": "",
        "_pending_delegations": [],
    }


# ── 测试：简单 ReAct 循环 ──


class TestSimpleReAct:
    """agent → tools → auto_verify → router → agent(纯文本) → END"""

    def test_read_file_then_respond(self, tmp_path):
        """LLM 先调用 read_file，再以文本回复结束"""
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        responses = [
            make_tool_call_msg([{
                "id": "tc1",
                "name": "read_file",
                "args": {"file_path": str(test_file)},
            }]),
            make_text_msg("文件内容是 print('hello')，这是一个简单的打印语句。"),
        ]

        llm = SequenceFakeLLM(responses=responses)

        # 构建只含 read_file 的工具列表（使用 langchain @tool）
        from langchain.tools import tool

        @tool
        def read_file(file_path: str) -> str:
            """读取文件内容"""
            with open(file_path, encoding="utf-8") as f:
                return f.read()

        graph = build_supervisor_graph(llm, [read_file])

        state = make_initial_state()
        result = graph.invoke(state)

        # 验证最终回复包含文件内容
        final_ai = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(final_ai) >= 2  # 至少一次工具调用 + 一次文本回复
        assert "hello" in final_ai[-1].content

    def test_no_tool_calls_immediate_end(self):
        """LLM 直接文本回复，不调用任何工具 → 立即结束"""
        responses = [make_text_msg("你好，有什么可以帮你的吗？")]
        llm = SequenceFakeLLM(responses=responses)

        graph = build_supervisor_graph(llm, [])

        state = make_initial_state()
        result = graph.invoke(state)

        final_ai = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(final_ai) == 1
        assert "你好" in final_ai[0].content


# ── 测试：计划创建 + 执行 ──


class TestPlanCreationAndExecution:
    """write_todo → update_todo(done) → update_todo(completed)"""

    def test_full_plan_lifecycle(self):
        """完整计划生命周期：创建 → 逐步执行 → 完成"""
        responses = [
            # 1. 创建计划
            make_tool_call_msg([{
                "id": "tc1",
                "name": "write_todo",
                "args": {"goal": "创建计算器", "steps": ["设计接口", "实现功能", "编写测试"]},
            }]),
            # 2. 完成第一步
            make_tool_call_msg([{
                "id": "tc2",
                "name": "update_todo",
                "args": {"step_index": 1, "status": "done", "result": "接口设计完成"},
            }]),
            # 3. 完成第二步
            make_tool_call_msg([{
                "id": "tc3",
                "name": "update_todo",
                "args": {"step_index": 2, "status": "done", "result": "功能实现完成"},
            }]),
            # 4. 标记计划完成
            make_tool_call_msg([{
                "id": "tc4",
                "name": "update_todo",
                "args": {"step_index": 0, "status": "completed"},
            }]),
            # 5. 最终回复
            make_text_msg("所有步骤已完成！"),
        ]

        llm = SequenceFakeLLM(responses=responses)

        # write_todo/update_todo 需要注册为 langchain 工具
        from langchain.tools import tool
        from pydantic import Field

        @tool
        def write_todo(goal: str, steps: list[str]) -> str:
            """创建执行计划"""
            return '{"status": "created"}'

        @tool
        def update_todo(step_index: int, status: str, result: str = "") -> str:
            """更新计划步骤状态"""
            return '{"status": "updated"}'

        graph = build_supervisor_graph(llm, [write_todo, update_todo])
        state = make_initial_state()
        result = graph.invoke(state)

        # 验证最终计划状态
        plan = result.get("current_plan")
        assert plan is not None
        assert plan["goal"] == "创建计算器"
        assert plan["status"] == "completed"

        # 验证最终文本回复
        final_messages = [m for m in result["messages"]
                          if isinstance(m, AIMessage) and not m.tool_calls]
        assert any("完成" in m.content for m in final_messages)


# ── 测试：auto_verify 失败修复循环 ──


class TestAutoVerifyFixLoop:
    """write_file → auto_verify(语法错误) → agent 修复 → auto_verify(通过) → router → END"""

    def test_verify_fail_then_fix(self, tmp_path):
        """写入语法错误的文件 → 验证失败 → 修复 → 验证通过"""
        target_file = tmp_path / "broken.py"

        responses = [
            # 1. 写入语法错误的文件
            make_tool_call_msg([{
                "id": "tc1",
                "name": "write_file",
                "args": {"file_path": str(target_file), "content": "def foo(:\n  pass"},
            }]),
            # 2. auto_verify 失败后，LLM 修复
            make_tool_call_msg([{
                "id": "tc2",
                "name": "write_file",
                "args": {"file_path": str(target_file), "content": "def foo():\n    pass\n"},
            }]),
            # 3. auto_verify 通过后，LLM 最终回复
            make_text_msg("已修复语法错误。"),
        ]

        llm = SequenceFakeLLM(responses=responses)

        from langchain.tools import tool

        @tool
        def write_file(file_path: str, content: str) -> str:
            """创建或覆盖文件"""
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"已写入 {file_path}"

        graph = build_supervisor_graph(llm, [write_file])
        state = make_initial_state()
        result = graph.invoke(state)

        # 验证文件最终内容正确（已修复）
        assert target_file.exists()
        content = target_file.read_text(encoding="utf-8")
        assert "def foo():" in content

        # 验证最终 verify_errors 为 None（已通过）
        assert result.get("verify_errors") is None

        # 验证有最终文本回复
        final_messages = [m for m in result["messages"]
                          if isinstance(m, AIMessage) and not m.tool_calls]
        assert any("修复" in m.content for m in final_messages)


# ── 测试：路由决策 ──


class TestRoutingDecisions:
    """测试路由函数的集成行为（不依赖 LLM 调用）"""

    def test_should_end_without_tool_calls(self):
        """无 tool_calls 且无 pending delegations → __end__"""
        from LangCode.agents.router import should_use_tools

        state = {"messages": [AIMessage(content="done")]}
        assert should_use_tools(state) == "__end__"

    def test_should_route_to_router_with_pending(self):
        """有 pending delegations → router"""
        from LangCode.agents.router import should_use_tools

        state = {
            "messages": [AIMessage(content="done")],
            "_pending_delegations": [{"route": "explore", "task": "search"}],
        }
        assert should_use_tools(state) == "router"

    def test_verify_routes_to_agent_on_error(self):
        """verify_errors 非空 → 回到 agent 修复"""
        from LangCode.agents.verify import after_verify_routing

        assert after_verify_routing({"verify_errors": ["syntax error"]}) == "agent"

    def test_verify_routes_to_router_on_success(self):
        """verify_errors 为空 → 继续到 router"""
        from LangCode.agents.verify import after_verify_routing

        assert after_verify_routing({"verify_errors": None}) == "router"

    def test_after_tools_routing_delegated(self):
        """有 pending delegations → delegated"""
        from LangCode.agents.router import after_tools_routing

        state = {"_pending_delegations": [{"route": "explore", "task": "t"}]}
        assert after_tools_routing(state) == "delegated"

    def test_after_tools_routing_react(self):
        """无 pending delegations → react"""
        from LangCode.agents.router import after_tools_routing

        assert after_tools_routing({}) == "react"


# ── 测试：dequeue + delegate_router 节点 ──


class TestDelegationNodes:
    """测试委派出队和路由节点的集成行为"""

    def test_dequeue_sets_route_and_task(self):
        """出队节点设置 route + task_description"""
        from LangCode.agents.graph_builder import _dequeue_delegation

        state = {
            "_pending_delegations": [
                {"route": "explore", "task": "搜索所有 Python 文件"},
            ],
        }
        result = _dequeue_delegation(state)

        assert result["route"] == "explore"
        assert result["task_description"] == "搜索所有 Python 文件"
        assert result["_pending_delegations"] == []

    def test_select_sub_agent_explore(self):
        """route=explore → sub_explore"""
        from LangCode.agents.graph_builder import _select_sub_agent

        assert _select_sub_agent({"route": "explore"}) == "sub_explore"

    def test_select_sub_agent_review(self):
        """route=review → sub_review"""
        from LangCode.agents.graph_builder import _select_sub_agent

        assert _select_sub_agent({"route": "review"}) == "sub_review"

    def test_select_sub_agent_unknown(self):
        """未知 route → __end__"""
        from LangCode.agents.graph_builder import _select_sub_agent

        assert _select_sub_agent({"route": "unknown"}) == "__end__"

    def test_multiple_delegations_fifo(self):
        """多次委派按 FIFO 顺序出队"""
        from LangCode.agents.graph_builder import _dequeue_delegation

        state = {
            "_pending_delegations": [
                {"route": "explore", "task": "第一个任务"},
                {"route": "review", "task": "第二个任务"},
            ],
        }

        # 第一次出队
        result1 = _dequeue_delegation(state)
        assert result1["route"] == "explore"
        assert result1["task_description"] == "第一个任务"
        assert len(result1["_pending_delegations"]) == 1

        # 第二次出队
        state2 = {**state, **result1}
        result2 = _dequeue_delegation(state2)
        assert result2["route"] == "review"
        assert result2["task_description"] == "第二个任务"
        assert len(result2["_pending_delegations"]) == 0


# ── 测试：process_tool_results 集成 ──


class TestProcessToolResultsIntegration:
    """测试工具结果处理的集成行为"""

    def test_delegate_explore_creates_pending(self):
        """delegate_explore 调用创建 pending delegation"""
        from LangCode.agents.router import process_tool_results, after_tools_routing

        state = {
            "messages": [AIMessage(content="", tool_calls=[{
                "id": "tc1",
                "name": "delegate_explore",
                "args": {"task": "搜索错误处理模式"},
            }])],
        }

        updates = process_tool_results(state)
        assert "_pending_delegations" in updates
        assert len(updates["_pending_delegations"]) == 1
        assert updates["_pending_delegations"][0]["route"] == "explore"

        # 路由应选择 delegated
        merged = {**state, **updates}
        assert after_tools_routing(merged) == "delegated"

    def test_write_todo_then_update_flow(self):
        """write_todo 后 update_todo 的完整流程"""
        from LangCode.agents.router import process_tool_results

        # 第一步：write_todo
        state1 = {
            "messages": [AIMessage(content="", tool_calls=[{
                "id": "tc1",
                "name": "write_todo",
                "args": {"goal": "重构", "steps": ["分析", "修改", "测试"]},
            }])],
        }
        updates1 = process_tool_results(state1)
        plan = updates1["current_plan"]
        assert plan["goal"] == "重构"
        assert len(plan["steps"]) == 3
        assert plan["steps"][0]["status"] == "in_progress"

        # 第二步：update_todo done
        state2 = {
            "messages": [AIMessage(content="", tool_calls=[{
                "id": "tc2",
                "name": "update_todo",
                "args": {"step_index": 1, "status": "done", "result": "分析完成"},
            }])],
            "current_plan": plan,
        }
        updates2 = process_tool_results(state2)
        plan2 = updates2["current_plan"]
        assert plan2["steps"][0]["status"] == "done"
        assert plan2["steps"][1]["status"] == "in_progress"


# ── 测试：Explore 子图结构 ──


class TestExploreSubgraph:
    """测试 Explore 子图的基本结构和路由"""

    def test_explore_routing_with_tool_calls(self):
        """Explore Agent: 有 tool_calls → tools"""
        from LangCode.agents.graph_builder import _explore_routing

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "id": "tc1", "name": "read_file", "args": {"file_path": "x.py"},
            }])
        ]}
        assert _explore_routing(state) == "tools"

    def test_explore_routing_without_tool_calls(self):
        """Explore Agent: 无 tool_calls → summarize"""
        from LangCode.agents.graph_builder import _explore_routing

        state = {"messages": [AIMessage(content="找到了")]}
        assert _explore_routing(state) == "summarize"

    def test_review_routing_needs_tool_round(self):
        """Review Agent: 无 tool_calls 但无历史工具调用 → tools（强制先搜索）"""
        from LangCode.agents.graph_builder import _review_agent_routing

        state = {"messages": [AIMessage(content="代码看起来不错")]}
        assert _review_agent_routing(state) == "tools"

    def test_review_routing_with_history_goes_to_report(self):
        """Review Agent: 无 tool_calls 且有历史工具调用 → report"""
        from LangCode.agents.graph_builder import _review_agent_routing

        state = {"messages": [
            AIMessage(content="", tool_calls=[{
                "id": "tc1", "name": "read_file", "args": {"file_path": "x.py"},
            }]),
            AIMessage(content="代码看起来不错"),
        ]}
        assert _review_agent_routing(state) == "report"


# ── 测试：完整图结构编译验证 ──


class TestGraphCompilation:
    """验证图编译成功且包含预期节点"""

    def test_main_graph_compiles_without_subgraphs(self):
        """主图可以不带子图编译"""
        llm = SequenceFakeLLM(responses=[])
        graph = build_supervisor_graph(llm, [])

        # LangGraph CompiledStateGraph 应该有节点
        node_names = list(graph.nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names
        assert "auto_verify" in node_names
        assert "router" in node_names
        assert "dequeue_delegation" in node_names

    def test_main_graph_compiles_with_subgraphs(self):
        """主图可以带子图编译"""
        llm = SequenceFakeLLM(responses=[])

        # 构建 explore 子图
        explore_graph = build_explore_subgraph(llm, [])

        graph = build_supervisor_graph(
            llm, [],
            sub_agent_graphs={"explore": explore_graph},
        )

        node_names = list(graph.nodes.keys())
        assert "agent" in node_names
        assert "sub_explore" in node_names
        assert "delegate_router" in node_names

    def test_explore_subgraph_compiles(self):
        """Explore 子图可以独立编译"""
        llm = SequenceFakeLLM(responses=[])
        graph = build_explore_subgraph(llm, [])

        node_names = list(graph.nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names
        assert "summarize" in node_names
        assert "summarize_llm" in node_names
