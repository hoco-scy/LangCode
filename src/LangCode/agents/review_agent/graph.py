"""ReviewAgent：专注于代码审查、安全分析、质量评估

图结构：agent → tools → report → END
报告节点在审查工具执行后自动生成结构化审查报告
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
1. 使用工具读取和分析目标代码
2. 工具执行后，系统会自动进入报告生成阶段
3. 报告阶段必须输出结构化的审查报告

## 可用工具
- `read_file` — 读取文件内容
- `search_files` — 搜索相关文件
- `run_python` — 运行代码验证行为
- `execute_shell` — 执行 shell 命令（如 linter）
- `git_log` — 查看提交历史
- `git_blame` — 查看代码修改历史

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


def _report_node(state: LCState) -> dict:
    """报告节点：注入报告生成指令，确保输出结构化审查报告"""
    return {"messages": [SystemMessage(
        content="[报告阶段] 审查信息收集完毕。请按照系统提示中的报告格式输出结构化审查报告。不要再调用工具，直接输出审查结果。确保包含严重程度统计和每个问题的具体位置。"
    )]}


def _report_llm_node(state: LCState, llm: ChatOpenAI) -> dict:
    """调用 LLM 生成审查报告"""
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def _agent_routing(state: LCState) -> Literal["tools", "report_prompt"]:
    """Agent 节点后路由：有工具调用则执行工具，否则进入报告生成"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "report_prompt"


class ReviewAgent(BaseAgent):
    name = "review"
    description = "代码审查员：审查代码质量、安全性，发现 bug，提供改进建议"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def build_graph(self) -> CompiledStateGraph:
        """ReviewAgent 专用图：agent → tools → agent → ... → report → END

        多轮工具调用后自动生成结构化审查报告
        """
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)
        builder.add_node("report_prompt", _report_node)
        builder.add_node("report_llm", lambda state: _report_llm_node(state, self.bound_llm))

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", _agent_routing)
        builder.add_edge("tools", "agent")
        builder.add_edge("report_prompt", "report_llm")
        builder.add_edge("report_llm", END)

        return builder.compile(checkpointer=self.checkpoint)

    def get_system_prompt(self) -> str:
        return REVIEW_AGENT_PROMPT
