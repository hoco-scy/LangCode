"""tools/base — 工具执行结果。

v2.1 变更：删除 Tool[Input,Output] ABC。
LangCode 基于 LangGraph 生态，工具统一使用 LangChain @tool 装饰器定义，
Tool ABC 是 Claude Code 架构的投影，在 LangGraph 中无不可替代职责。

保留 ToolResult：StreamingToolExecutor 和 MCP 适配器需要结果封装。
"""

from __future__ import annotations

from typing import Optional, Any


class ToolResult:
    """工具执行结果。

    - data: 工具输出数据（通常为 str）
    - new_messages: 可选附加消息（注入到对话历史）
    - context_modifier: 上下文修改器（如切换工作目录，仅非并发安全工具可用）
    """

    def __init__(
        self,
        data: Any,
        new_messages: Optional[list] = None,
        context_modifier: Optional[Any] = None,
    ):
        self.data = data
        self.new_messages = new_messages or []
        self.context_modifier = context_modifier
