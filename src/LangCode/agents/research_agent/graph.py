"""ResearchAgent：专注于文件搜索、阅读、信息总结"""

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Checkpointer

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
2. 搜索相关文件
3. 阅读和分析代码
4. 总结发现

## 可用工具
- `read_file` — 读取文件内容
- `search_files` — 使用 glob 模式搜索文件
- `fetch_api` — 请求外部 API（查阅文档）
- `memory_search` — 搜索长期记忆

## 行为准则
- 系统性地搜索，不要遗漏关键文件
- 阅读代码时关注结构、模式和设计决策
- 总结要简洁但全面
- 标注文件路径便于后续引用
"""


class ResearchAgent(BaseAgent):
    name = "research"
    description = "代码研究员：搜索、阅读、分析代码库，总结发现和生成报告"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def get_system_prompt(self) -> str:
        return RESEARCH_AGENT_PROMPT
