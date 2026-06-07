"""记忆相关工具：供 Agent 调用的记忆操作"""

from typing import Optional
from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("memory.tools")

# 全局引用，由 main.py 初始化后注入
_store = None
_manager = None


def init_memory_tools(store, manager):
    """由 main.py 调用，注入 store 和 manager 实例"""
    global _store, _manager
    _store = store
    _manager = manager


class MemorySaveInput(BaseModel):
    content: str = Field(description="要保存的记忆内容")
    memory_type: str = Field(default="fact", description="记忆类型: fact(事实)/preference(偏好)/project(项目)/skill(技能)")
    tags: list[str] = Field(default_factory=list, description="标签列表，便于检索")


@tool("memory_save", args_schema=MemorySaveInput)
def memory_save(content: str, memory_type: str = "fact", tags: list[str] = None) -> dict:
    """保存一条长期记忆。用于记住用户的偏好、项目决策、重要事实等跨会话信息。"""
    if _store is None:
        return {"success": False, "error": "记忆系统未初始化"}
    try:
        from LangCode.memory.store import MemoryRecord
        record = MemoryRecord(content=content, memory_type=memory_type, tags=tags or [])
        rid = _store.save(record)
        log.info("memory_save: id=%s type=%s", rid, memory_type)
        return {"success": True, "id": rid, "message": f"记忆已保存 (id={rid})"}
    except Exception as e:
        log.error("memory_save 失败: %s", e)
        return {"success": False, "error": str(e)}


class MemorySearchInput(BaseModel):
    query: str = Field(description="搜索关键词或描述")
    top_k: int = Field(default=5, description="返回结果数量")


@tool("memory_search", args_schema=MemorySearchInput)
def memory_search(query: str, top_k: int = 5) -> dict:
    """搜索长期记忆。用于查找之前保存的偏好、项目信息、技能经验等。"""
    if _store is None:
        return {"success": False, "error": "记忆系统未初始化"}
    try:
        records = _store.search(query, top_k=top_k)
        if not records:
            return {"success": True, "results": [], "message": "未找到相关记忆"}
        results = [
            {"id": r.id, "content": r.content, "type": r.memory_type, "tags": r.tags}
            for r in records
        ]
        log.info("memory_search: query='%s' 找到 %d 条", query, len(results))
        return {"success": True, "results": results}
    except Exception as e:
        log.error("memory_search 失败: %s", e)
        return {"success": False, "error": str(e)}


class MemoryListInput(BaseModel):
    memory_type: Optional[str] = Field(default=None, description="按类型过滤，为空则列出全部")


@tool("memory_list", args_schema=MemoryListInput)
def memory_list(memory_type: Optional[str] = None) -> dict:
    """列出所有长期记忆，可按类型过滤。"""
    if _store is None:
        return {"success": False, "error": "记忆系统未初始化"}
    try:
        records = _store.list_all(memory_type=memory_type)
        results = [
            {"id": r.id, "content": r.content, "type": r.memory_type, "tags": r.tags, "created_at": r.created_at}
            for r in records
        ]
        total = _store.count()
        log.info("memory_list: type=%s 返回 %d/%d 条", memory_type, len(results), total)
        return {"success": True, "results": results, "total": total}
    except Exception as e:
        log.error("memory_list 失败: %s", e)
        return {"success": False, "error": str(e)}
