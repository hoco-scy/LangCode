"""Tool<I,O> — 统一工具抽象接口。

参考 Claude Code Tool.ts 设计：
1. 类型参数化: Input Pydantic Model, Output Pydantic Model
2. 输入驱动的属性推断: is_concurrency_safe(input), is_read_only(input)
3. 自包含权限检查: check_permissions 是 Tool 自身的方法
4. 渐进式增强: 大量方法可选（默认安全值）

用法：
    class MyTool(Tool[MyInput, MyOutput]):
        name = "my_tool"
        description = "..."
        input_schema = MyInput

        async def call(self, args, context):
            return ToolResult(data=...)

        def check_permissions(self, args, context):
            return PermissionResult.allow()

        def is_read_only(self, args):
            return True
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, Any, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from LangCode.tools.context import ToolUseContext

Input = TypeVar("Input", bound=BaseModel)
Output = TypeVar("Output")


class ToolResult(Generic[Output]):
    """工具执行结果。

    参考 Claude Code ToolResult<T> 设计：
    - data: 工具输出数据
    - new_messages: 可选的附加消息（注入到对话历史）
    - context_modifier: 上下文修改器（仅非并发安全工具可用）

    context_modifier 的设计精妙之处：
    某些工具执行后会改变后续工具的执行环境（如切换工作目录）。
    通过返回一个上下文修改函数而非直接修改全局状态，保证了并发安全性。
    """

    def __init__(
        self,
        data: Output,
        new_messages: Optional[list] = None,
        context_modifier: Optional[Any] = None,
    ):
        self.data = data
        self.new_messages = new_messages or []
        self.context_modifier = context_modifier


class Tool(ABC, Generic[Input, Output]):
    """工具抽象基类。

    每个具体工具必须实现:
    - name: 工具唯一标识
    - description: 工具功能描述（给 LLM 看的）
    - input_schema: Pydantic Input 模型类
    - call(): 核心执行方法
    - check_permissions(): 权限检查方法

    可覆盖（默认安全值）:
    - is_concurrency_safe(): 是否可并行（默认 False）
    - is_read_only(): 是否只读（默认 False）
    - is_destructive(): 是否破坏性操作（默认 False）
    - validate_input(): 额外输入验证（默认无）
    - to_langchain_tool(): 转换为 LangChain BaseTool
    - to_openai_schema(): 生成 OpenAI function calling schema

    设计原则：
    - 输入驱动的属性推断：同一工具（如 BashTool）根据输入不同，
      可以是只读（ls）也可以是破坏性（rm -rf /）
    - 权限检查在工具内部定义，权限系统（permissions/）提供全局规则覆盖
    """

    name: str
    description: str
    input_schema: type[BaseModel]

    # ── 生命周期方法（必须实现） ──

    @abstractmethod
    async def call(
        self, args: Input, context: "ToolUseContext"
    ) -> ToolResult[Output]:
        """核心执行方法。

        Args:
            args: 验证后的输入参数（已通过 input_schema 验证）
            context: 工具执行上下文（依赖注入载体）

        Returns:
            ToolResult 包含输出数据和可选的附加消息
        """
        ...

    @abstractmethod
    def check_permissions(
        self, args: Input, context: "ToolUseContext"
    ) -> "PermissionResult":
        """权限检查 — 每个工具自行定义。

        PermissionResult 可以是:
        - allow(): 允许执行
        - deny(): 拒绝执行
        - ask(): 需要用户确认

        注意：这里只包含工具特有的权限逻辑。
        通用权限检查（基于规则的匹配）在 permissions/rules.py 中处理。
        """
        ...

    # ── 输入验证（可选覆盖） ──

    def validate_input(
        self, args: Input, context: "ToolUseContext"
    ) -> list[str]:
        """额外输入验证（覆盖实现）。

        Args:
            args: 已通过 Pydantic 验证的输入

        Returns:
            错误描述列表。空列表表示验证通过。
        """
        return []

    # ── 分类属性（输入驱动！） ──

    def is_concurrency_safe(self, args: Input) -> bool:
        """是否可以与其他并发安全工具并行执行？

        参考 Claude Code:
        "Only mark as concurrency-safe when the tool performs read-only
         operations that cannot interfere with each other."
        默认 False（安全优先）。
        """
        return False

    def is_read_only(self, args: Input) -> bool:
        """是否只读操作？影响 plan 模式下的可用性。"""
        return False

    def is_destructive(self, args: Input) -> bool:
        """是否破坏性操作（删除、覆盖、发送）？

        参考 Claude Code:
        "Only set when the tool performs irreversible operations
         (delete, overwrite, send)."
        影响安全分类器判断和 UI 警告提示。
        """
        return False

    def requires_user_confirmation(self, args: Input) -> bool:
        """是否需要用户交互确认？"""
        return False

    # ── Schema 生成 ──

    def to_langchain_tool(self) -> Any:
        """转换为 LangChain BaseTool（用于 bind_tools）。

        默认实现：使用 @tool 装饰器包装。
        子类可覆盖以提供自定义实现。
        """
        from langchain.tools import tool as langchain_tool

        input_model = self.input_schema
        description = self.description
        tool_instance = self

        # 创建同步包装函数
        def _tool_fn(**kwargs) -> str:
            """LangChain tool wrapper"""
            import asyncio
            args = input_model(**kwargs)
            # 创建临时 context（实际运行时从 ToolUseContext 注入）
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
            result = asyncio.run(tool_instance.call(args, None))
            return str(result.data) if result.data else ""

        _tool_fn.__name__ = self.name
        _tool_fn.__doc__ = description

        return langchain_tool(self.name, args_schema=input_model)(_tool_fn)

    def to_openai_schema(self) -> dict:
        """生成 OpenAI function calling schema。

        使用 Pydantic 的 model_json_schema() 生成 JSON Schema。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }
