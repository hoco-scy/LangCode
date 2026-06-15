"""FileReadTool — 读取文件内容，支持指定行号范围分段读取。"""

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.file_read")


class ReadFileInput(BaseModel):
    file_path: str = Field(description="The path to the file to read")
    offset: int = Field(default=1, ge=1, description="起始行号（从 1 开始），默认为 1")
    limit: int = Field(default=500, ge=1, le=2000, description="最大读取行数，默认 500，上限 2000")
    encode: str = Field(default="utf-8", description="The encoding of the file")


@tool("read_file", args_schema=ReadFileInput)
def read_file(file_path: str, offset: int = 1, limit: int = 500, encode: str = "utf-8"):
    """读取文件内容，支持指定行号范围分段读取"""
    from LangCode.shared.models import FileContentResponse
    log.info("read_file: file_path=%s offset=%d limit=%d encode=%s", file_path, offset, limit, encode)
    try:
        with open(file_path, mode="r", encoding=encode) as f:
            lines = f.readlines()
        total_lines = len(lines)
        start = offset - 1
        end = min(start + limit, total_lines)
        if start >= total_lines:
            log.warning("read_file 失败: offset=%d 超出总行数 %d", offset, total_lines)
            return FileContentResponse(
                content="", success=False, file_path=file_path,
                error=f"offset={offset} 超出文件总行数 {total_lines}"
            )
        content = "".join(lines[start:end])
        log.debug("read_file 成功: lines=%d-%d/%d, %d 字符", offset, offset + len(lines[start:end]) - 1, total_lines, len(content))
        return FileContentResponse(
            content=content, success=True, file_path=file_path,
            bytes_read=len(content.encode(encode))
        )
    except FileNotFoundError:
        log.warning("read_file 失败: 文件不存在 %s", file_path)
        return FileContentResponse(content="", success=False, error="File not found")
    except UnicodeDecodeError:
        log.warning("read_file 失败: 编码错误 %s", file_path)
        return FileContentResponse(content="", success=False, error="Encoding error")
    except Exception as e:
        log.error("read_file 异常: %s", e)
        return FileContentResponse(content="", success=False, error=str(e))
