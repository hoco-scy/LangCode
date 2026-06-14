"""FileEditTool — 精确替换文件中的指定文本。"""

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.file_edit")


class EditFileInput(BaseModel):
    file_path: str = Field(description="要编辑的文件路径")
    old_text: str = Field(description="要被替换的原始文本（必须精确匹配文件中的内容）")
    new_text: str = Field(description="替换后的新文本")


@tool("edit_file", args_schema=EditFileInput)
def edit_file(file_path: str, old_text: str, new_text: str):
    """精确替换文件中的指定文本。old_text 必须与文件中的内容完全匹配（包括缩进和换行）。"""
    from LangCode.shared.models import EditResponse
    log.info("edit_file: file_path=%s old_len=%d new_len=%d", file_path, len(old_text), len(new_text))
    try:
        with open(file_path, mode="r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_text)
        if count == 0:
            log.warning("edit_file: 未找到匹配文本")
            return EditResponse(success=False, error="未在文件中找到匹配的文本，请检查 old_text 是否精确匹配")
        if count > 1:
            log.warning("edit_file: 匹配到 %d 处，需要唯一匹配", count)
            return EditResponse(success=False, error=f"匹配到 {count} 处相同文本，请提供更精确的上下文使其唯一")

        new_content = content.replace(old_text, new_text, 1)
        with open(file_path, mode="w", encoding="utf-8") as f:
            f.write(new_content)
        log.debug("edit_file 成功: %s", file_path)
        return EditResponse(success=True, file_path=file_path)
    except FileNotFoundError:
        log.warning("edit_file: 文件不存在 %s", file_path)
        return EditResponse(success=False, error=f"文件不存在: {file_path}")
    except Exception as e:
        log.error("edit_file 异常: %s", e)
        return EditResponse(success=False, error=str(e))
