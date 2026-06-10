"""工具响应的结构化 Pydantic 模型

所有工具返回类型化的响应模型，让 LLM 能更准确地解析结果。
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ToolResponse(BaseModel):
    """工具响应基类，兼容 dict 风格访问（result["key"]）"""
    success: bool = Field(description="操作是否成功")
    error: Optional[str] = Field(default=None, description="错误信息（success=False 时）")

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __contains__(self, key):
        return hasattr(self, key)


class FileContentResponse(ToolResponse):
    """文件读取响应"""
    content: Optional[str] = Field(default=None, description="文件内容")
    file_path: Optional[str] = Field(default=None, description="文件路径")
    bytes_read: Optional[int] = Field(default=None, description="读取的字节数")


class WriteResponse(ToolResponse):
    """文件写入响应"""
    file_path: Optional[str] = Field(default=None, description="写入的文件路径")
    bytes_written: Optional[int] = Field(default=None, description="写入的字节数")


class EditResponse(ToolResponse):
    """文件编辑响应"""
    file_path: Optional[str] = Field(default=None, description="编辑的文件路径")


class SearchResponse(ToolResponse):
    """文件搜索响应"""
    files: list[str] = Field(default_factory=list, description="匹配的文件路径列表")
    total: int = Field(default=0, description="匹配总数")


class CommandResponse(ToolResponse):
    """命令执行响应"""
    output: Optional[str] = Field(default=None, description="标准输出")
    return_code: Optional[int] = Field(default=None, description="退出码")


class PythonResponse(ToolResponse):
    """Python 执行响应"""
    output: Optional[str] = Field(default=None, description="标准输出")


class GitStatusResponse(ToolResponse):
    """Git 状态响应"""
    status: Optional[str] = Field(default=None, description="工作区状态")


class GitDiffResponse(ToolResponse):
    """Git 差异响应"""
    diff: Optional[str] = Field(default=None, description="变更差异内容")
    lines: Optional[int] = Field(default=None, description="差异行数")


class GitCommitInfo(BaseModel):
    """单个提交信息"""
    hash: str = Field(description="提交哈希")
    message: str = Field(description="提交消息")


class GitLogResponse(ToolResponse):
    """Git 日志响应"""
    commits: list[GitCommitInfo] = Field(default_factory=list, description="提交列表")
    total: int = Field(default=0, description="返回的提交数")


class GitBlameEntry(BaseModel):
    """Blame 条目"""
    reference: str = Field(description="作者和提交摘要")
    lines: int = Field(description="涉及行数")


class GitBlameResponse(ToolResponse):
    """Git Blame 响应"""
    file: Optional[str] = Field(default=None, description="文件路径")
    blame: list[GitBlameEntry] = Field(default_factory=list, description="blame 条目列表")
