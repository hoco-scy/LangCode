from typing import Literal, Annotated, TypedDict
import pydantic
from langgraph.graph import StateGraph, END, add_messages
from langgraph.types import interrupt, Command
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage

class LCState(TypedDict):

    # 对话相关状态，
    messages: Annotated[list[AnyMessage], add_messages]  # 对话历史

    # 用户信息相关状态
    user_name: str                           # 用户姓名

    platform: Literal["windows", "linux", "mac"]  # 用户操作系统平台
    
    # 工具相关状态
    tool_retry_count: int   # 工具重试次数

    # 当前智能体状态
    current_agent: Literal["supervisor"]  # 当前智能体名称

    # dangerous 状态
    dangerous_edit_mode: bool   # 是否处于危险状态（所有编辑自动接受，不做审查）
    
    # STRICT_MODE 状态
    strict_mode: bool  # 是否处于严格模式（所有生成的代码都需要审查）

    # 内容生成相关状态
    content_generation_count: int  # 内容生成次数
    tool_calls_count: int   # 工具调用次数
    code_generation_count: int   # 代码生成次数