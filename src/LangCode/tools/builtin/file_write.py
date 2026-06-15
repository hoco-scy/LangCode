"""FileWriteTool — 写入文件内容，自动创建父目录。"""

import os
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.file_write")


class WriteFileInput(BaseModel):
    file_path: str = Field(description="要写入的文件路径")
    content: str = Field(description="要写入的内容")
    encode: str = Field(default="utf-8", description="文件编码")


@tool("write_file", args_schema=WriteFileInput)
def write_file(file_path: str, content: str, encode: str = "utf-8"):
    """写入文件内容，如果文件不存在会自动创建（包括父目录）"""
    from LangCode.shared.models import WriteResponse
    log.info("write_file: file_path=%s len=%d", file_path, len(content))
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, mode="w", encoding=encode) as f:
            f.write(content)
        log.debug("write_file 成功: %s", file_path)
        return WriteResponse(success=True, file_path=file_path, bytes_written=len(content.encode(encode)))
    except Exception as e:
        log.error("write_file 失败: %s", e)
        return WriteResponse(success=False, error=str(e))
