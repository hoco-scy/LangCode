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


class FetchAPIResponse(ToolResponse):
    """API 请求响应"""
    content: Optional[str] = Field(default=None, description="响应体内容")
    status_code: Optional[int] = Field(default=None, description="HTTP 状态码")


# ============================================================
#  AST 工具响应模型
# ============================================================

class AstFunctionInfo(BaseModel):
    """函数信息"""
    name: str = Field(description="函数名")
    line: int = Field(description="起始行号")
    params: list[str] = Field(default_factory=list, description="参数名列表")

    def __getitem__(self, key):
        return getattr(self, key)


class AstClassInfo(BaseModel):
    """类信息"""
    name: str = Field(description="类名")
    line: int = Field(description="起始行号")
    methods: list[str] = Field(default_factory=list, description="方法名列表")

    def __getitem__(self, key):
        return getattr(self, key)


class AstInfoResponse(ToolResponse):
    """AST 结构分析响应"""
    file: Optional[str] = Field(default=None, description="文件路径")
    functions: list[AstFunctionInfo] = Field(default_factory=list, description="函数列表")
    classes: list[AstClassInfo] = Field(default_factory=list, description="类列表")
    imports: list[str] = Field(default_factory=list, description="import 语句列表")
    total_lines: Optional[int] = Field(default=None, description="文件总行数")


class AstFindResult(BaseModel):
    """AST 查找结果条目"""
    name: str = Field(description="名称")
    type: str = Field(description="类型: function/class/method/variable")
    line: int = Field(description="起始行号")
    end_line: Optional[int] = Field(default=None, description="结束行号")
    class_name: Optional[str] = Field(default=None, description="所属类名（仅 method 类型）")
    text_preview: Optional[str] = Field(default=None, description="代码预览")

    def __getitem__(self, key):
        return getattr(self, key)


class AstFindResponse(ToolResponse):
    """AST 查找响应"""
    file: Optional[str] = Field(default=None, description="文件路径")
    query: Optional[str] = Field(default=None, description="查询描述")
    found: int = Field(default=0, description="找到的数量")
    results: list[AstFindResult] = Field(default_factory=list, description="结果列表")


class AstEditResponse(ToolResponse):
    """AST 编辑操作响应（重命名、添加参数、添加方法、添加 import）"""
    message: Optional[str] = Field(default=None, description="操作结果描述")
    changes: list[str] = Field(default_factory=list, description="变更详情列表")
