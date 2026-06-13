"""ResearchAgent：专注于文件搜索、阅读、信息分析

图结构：agent → tools → agent → ... → synthesize → END
多轮信息收集后，synthesize 节点强制输出结构化研究报告。
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

log = get_logger("agents.research")

RESEARCH_AGENT_PROMPT = """你是一个专业的代码研究分析 Agent。

## 职责
- 搜索和阅读代码库
- 分析代码结构和模式
- 总结发现和生成报告
- 查找特定功能、模式或问题

## 工作方式
1. 理解研究目标
2. 使用搜索和阅读工具收集信息
3. 可以多轮调用工具，确保信息充分
4. 当你认为信息收集足够时，不调用任何工具，系统会自动进入报告生成阶段
5. 在报告生成阶段，输出结构化研究报告

## 输出格式
完成研究后，输出结构化报告：
```
## 研究报告

### 研究目标
[目标描述]

### 关键发现
1. [发现 1]
2. [发现 2]
...

### 代码结构
- [模块/文件] — [作用描述]

### 关键模式与设计决策
- [模式 1]

### 建议
- [可操作的建议]
```

## 行为准则
- 系统性地搜索，不要遗漏关键文件
- 阅读代码时关注结构、模式和设计决策
- 善用 execute_shell 执行 git log / git blame 等命令了解代码变更历史
- 善用 memory_search 查找之前保存的相关记忆
- 总结要简洁但全面，标注文件路径便于后续引用
"""

SYNTHESIZE_PROMPT = """[报告生成阶段] 信息收集完毕。

请基于以上的工具调用结果和分析，按照输出格式生成结构化的研究报告。
不要再调用工具，直接输出报告。确保：
1. 所有发现都有文件路径引用
2. 建议是可操作的
3. 报告结构完整"""


def _synthesize_node(state: LCState) -> dict:
    """合成节点：注入报告生成指令"""
    return {"messages": [SystemMessage(content=SYNTHESIZE_PROMPT)]}


class ResearchAgent(BaseAgent):
    name = "research"
    description = "代码研究员：搜索、阅读、分析代码库，总结发现和生成报告"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def build_graph(self) -> CompiledStateGraph:
        """ResearchAgent 专用图：agent → tools → agent → ... → synthesize → END"""
        builder = StateGraph(LCState)
        tool_node = ToolNode(tools=self.tools)

        builder.add_node("agent", self._call_llm)
        builder.add_node("tools", tool_node)
        builder.add_node("synthesize", _synthesize_node)
        builder.add_node("synthesize_llm", lambda state: self._call_llm(state))

        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", self._agent_routing, {
            "tools": "tools",
            "synthesize": "synthesize",
        })
        builder.add_edge("tools", "agent")
        builder.add_edge("synthesize", "synthesize_llm")
        builder.add_edge("synthesize_llm", END)

        return builder.compile(checkpointer=self.checkpoint)

    def _agent_routing(self, state: LCState) -> Literal["tools", "synthesize"]:
        """Agent 节点后路由：有工具调用则继续收集，否则进入合成"""
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return "synthesize"

    def get_system_prompt(self) -> str:
        return RESEARCH_AGENT_PROMPT
