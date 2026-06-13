"""Delegate 工具：将子Agent委派暴露为 LLM 可调用的工具

核心改动：不再依赖 [route: code task: ...] 文本标签来识别委派，
而是让 LLM 通过 tool calling 调用 delegate_code/research/review 工具。
统一的工具调用模型消除了非标准格式的解析不可靠问题。
"""

import json
from langchain.tools import tool
from pydantic import BaseModel, Field


class DelegateInput(BaseModel):
    task: str = Field(description="委派给子Agent的具体任务描述")


@tool("delegate_code", args_schema=DelegateInput)
def delegate_code(task: str) -> str:
    """将代码编写或修改任务委派给代码专家Agent。适用于需要编写新代码、修改现有代码、调试等场景。"""
    return json.dumps({"agent": "code", "task": task}, ensure_ascii=False)


@tool("delegate_research", args_schema=DelegateInput)
def delegate_research(task: str) -> str:
    """将代码分析或研究任务委派给研究Agent。适用于需要阅读代码、搜索文件、分析项目结构等场景。"""
    return json.dumps({"agent": "research", "task": task}, ensure_ascii=False)


@tool("delegate_review", args_schema=DelegateInput)
def delegate_review(task: str) -> str:
    """将代码审查任务委派给审查Agent。适用于代码质量审查、安全分析等场景。"""
    return json.dumps({"agent": "review", "task": task}, ensure_ascii=False)


delegate_tools = [delegate_code, delegate_research, delegate_review]
