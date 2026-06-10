"""ReviewAgent：专注于代码审查、安全分析、质量评估

图结构：agent → tools → agent → ... → report → END
多轮工具调用后自动进入报告生成阶段，使用不绑定工具的 LLM 防止幻觉 tool_calls。
"""

from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer

from LangCode.shared.state import LCState
from LangCode.shared.logger import get_logger
from LangCode.agents.base import BaseAgent

log = get_logger("agents.review")

REVIEW_AGENT_PROMPT = """你是一个专业的代码审查 Agent。

## 职责
- 审查代码质量、可读性、可维护性
- 发现潜在的 bug 和安全漏洞
- 评估代码是否符合最佳实践
- 提供改进建议

## 工作方式
1. 使用工具读取和分析目标代码（至少一轮工具调用）
2. 可以多轮调用工具，确保审查全面
3. 当你认为审查信息收集足够时，不调用任何工具，系统会自动进入报告生成阶段
4. 在报告生成阶段，必须输出结构化的审查报告

## 审查维度
- **正确性**: 逻辑是否正确，边界条件是否处理
- **安全性**: 是否有注入、越权、信息泄露风险
- **可读性**: 命名、结构、注释是否清晰
- **性能**: 是否有明显的性能问题
- **可维护性**: 是否易于修改和扩展
- **测试**: 是否有充分的测试覆盖

## 输出格式
审查完成后，输出结构化报告：
```
## 审查报告

### 总体评价
[一句话总结]

### 严重程度统计
- 高: X 个
- 中: X 个
- 低: X 个

### 发现的问题
1. [严重程度: 高/中/低] [文件:行号] [问题描述]
   建议: [改进建议]

### 优点
- [值得肯定的地方]

### 建议
- [总体改进建议]
```
"""

REPORT_PROMPT = """[报告阶段] 审查信息收集完毕。

请按照系统提示中的报告格式输出结构化审查报告。不要再调用工具，直接输出审查结果。
确保包含：总体评价、严重程度统计、每个问题的具体位置和建议、优点、总体改进建议。"""

MIN_REVIEW_ROUNDS = 1  # 至少经过一轮工具调用才能进入报告阶段


def _report_node(state: LCState, raw_llm: ChatOpenAI) -> dict:
    """报告节点：注入报告指令并调用不绑定工具的 LLM 生成报告"""
    messages = list(state["messages"])
    messages.append(SystemMessage(content=REPORT_PROMPT))
    response = raw_llm.invoke(messages)
    return {"messages": [response]}


class ReviewAgent(BaseAgent):
    name = "review"
    description = "代码审查员：审查代码质量、安全性，发现 bug，提供改进建议"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def build_graph(self) -> CompiledStateGraph:
        """ReviewAgent 专用图：agent → tools → agent → ... → report → END

        多轮工具调用后自动生成结构化审查报告。
        报告阶段使用 raw LLM（不绑定工具），防止 LLM 幻觉调用工具。
        """
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)
        builder.add_node("report", lambda state: _report_node(state, self.llm))

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", self._agent_routing, {
            "tools": "tools",
            "report": "report",
        })
        builder.add_edge("tools", "agent")
        builder.add_edge("report", END)

        return builder.compile(checkpointer=self.checkpoint)

    def _agent_routing(self, state: LCState) -> Literal["tools", "report"]:
        """Agent 节点后路由：至少一轮工具调用后才能进入报告阶段"""
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"

        # 检查是否已经进行过工具调用（至少一轮）
        tool_count = sum(
            1 for m in state["messages"]
            if hasattr(m, "tool_calls") and m.tool_calls
        )
        if tool_count >= MIN_REVIEW_ROUNDS:
            return "report"
        # 还没有工具调用，不能进入报告阶段，回到 agent
        return "tools"

    def get_system_prompt(self) -> str:
        return REVIEW_AGENT_PROMPT
