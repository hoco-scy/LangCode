"""state — 状态管理。

- store: _StoreOps 极简响应式容器
- app_state: AppState 全局应用状态
- session: SessionStore 会话元数据存储
- compact: ContextCompactor 三层上下文压缩
"""

from LangCode.state.store import create_store
from LangCode.state.session import SessionStore, SessionRecord
from LangCode.state.compact import ContextCompactor

__all__ = ["create_store", "SessionStore", "SessionRecord", "ContextCompactor"]
