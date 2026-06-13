"""agents/supervisor/router.py — Agent-as-Entry 路由决策测试"""

from langchain_core.messages import AIMessage

from LangCode.agents.supervisor.router import (
    AgentDecision, extract_decision_from_agent, plan_create_from_agent,
    should_create_plan, delegate_routing, MAX_SUPERVISOR_ITERATIONS,
)
from LangCode.planning.schema import Plan, PlanStep


class TestAgentDecision:
    def test_schema_fields(self):
        d = AgentDecision(content="回答", reasoning="简单任务", plan_steps=[])
        assert d.content == "回答"
        assert d.reasoning == "简单任务"
        assert d.plan_steps == []

    def test_plan_steps(self):
        d = AgentDecision(content="", plan_steps=["步骤A", "步骤B"])
        assert len(d.plan_steps) == 2


class TestExtractDecisionFromAgent:
    def test_tool_calls_returns_react(self):
        msg = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "tc1"}])
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "react"

    def test_plain_text_returns_end(self):
        msg = AIMessage(content="你好，有什么可以帮助你的？")
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "end"

    def test_plan_steps_returns_plan(self):
        msg = AIMessage(content="执行计划：\n1. 步骤A\n2. 步骤B")
        msg._plan_steps = ["步骤A", "步骤B"]
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "plan"
        assert result["plan_steps"] == ["步骤A", "步骤B"]

    def test_route_tag_returns_delegate(self):
        msg = AIMessage(content="[route: code task: 写 hello world] 马上开始")
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "code"
        assert "写 hello world" in result["task_description"]

    def test_research_route_tag(self):
        msg = AIMessage(content="[route: research task: 分析代码结构]")
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "research"

    def test_review_route_tag(self):
        msg = AIMessage(content="[route: review task: 审查安全性]")
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "review"

    def test_empty_messages_returns_end(self):
        state = {"messages": []}
        result = extract_decision_from_agent(state)
        assert result["route"] == "end"

    def test_plan_steps_via_additional_kwargs(self):
        msg = AIMessage(content="计划如下")
        msg.additional_kwargs = {"plan_steps": ["步骤1", "步骤2"]}
        state = {"messages": [msg]}
        result = extract_decision_from_agent(state)
        assert result["route"] == "plan"
        assert result["plan_steps"] == ["步骤1", "步骤2"]


class TestPlanCreateFromAgent:
    def test_creates_plan_from_steps(self):
        state = {
            "plan_steps": ["分析代码", "编写实现", "运行测试"],
            "task_description": "重构模块",
        }
        result = plan_create_from_agent(state)
        assert "current_plan" in result
        plan = Plan(**result["current_plan"])
        assert plan.goal == "重构模块"
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "分析代码"
        assert result["agent_mode"] == "build"

    def test_empty_steps_returns_empty(self):
        state = {"plan_steps": [], "task_description": ""}
        result = plan_create_from_agent(state)
        assert result == {}

    def test_missing_steps_returns_empty(self):
        state = {"task_description": "任务"}
        result = plan_create_from_agent(state)
        assert result == {}


class TestShouldCreatePlan:
    def test_plan_route_with_steps(self):
        state = {"route": "plan", "plan_steps": ["A", "B"]}
        assert should_create_plan(state) == "plan_create"

    def test_plan_route_without_steps(self):
        state = {"route": "plan", "plan_steps": []}
        assert should_create_plan(state) == "__end__"

    def test_react_route(self):
        state = {"route": "react"}
        assert should_create_plan(state) == "__end__"

    def test_end_route(self):
        state = {"route": "end"}
        assert should_create_plan(state) == "__end__"


class TestDelegateRouting:
    def test_code_route(self):
        state = {"route": "code"}
        assert delegate_routing(state) == "code_agent"

    def test_research_route(self):
        state = {"route": "research"}
        assert delegate_routing(state) == "research_agent"

    def test_review_route(self):
        state = {"route": "review"}
        assert delegate_routing(state) == "review_agent"

    def test_react_route_returns_end(self):
        state = {"route": "react"}
        assert delegate_routing(state) == "__end__"

    def test_end_route(self):
        state = {"route": "end"}
        assert delegate_routing(state) == "__end__"
