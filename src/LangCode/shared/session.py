"""会话元数据存储：按工作区管理会话索引

消息正文由 LangGraph SqliteSaver checkpoint 自动持久化，
本模块只存索引元数据（id、workspace、title、时间戳），供 /session 命令查询和切换。
"""

import uuid
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from LangCode.shared.logger import get_logger

log = get_logger("shared.session")


class SessionRecord(BaseModel):
    """会话元数据"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace: str
    title: str = "新对话"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionStore:
    """基于 SQLite 的会话元数据索引"""

    def __init__(self, db_path: str = str(Path.home() / ".langcode" / "sessions.db")):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()
        log.info("SessionStore 初始化: %s", self.db_path)

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                workspace  TEXT NOT NULL,
                title      TEXT NOT NULL DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_workspace
                ON sessions(workspace, updated_at DESC);
        """)
        self._conn.commit()

    def save(self, record: SessionRecord):
        """保存或更新会话元数据"""
        now = datetime.now(timezone.utc).isoformat()
        record.updated_at = now
        with self._lock:
            self._conn.execute(
                """INSERT INTO sessions (id, workspace, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, updated_at=excluded.updated_at""",
                (record.id, record.workspace, record.title, record.created_at, now),
            )
            self._conn.commit()

    def get(self, session_id: str, workspace: str) -> Optional[SessionRecord]:
        """按 id + workspace 查询单个会话"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND workspace = ?",
                (session_id, workspace),
            ).fetchone()
        if not row:
            return None
        return SessionRecord(
            id=row["id"], workspace=row["workspace"], title=row["title"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_sessions(self, workspace: str, limit: int = 20) -> list[SessionRecord]:
        """列出工作区下的最近会话"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE workspace = ? ORDER BY updated_at DESC LIMIT ?",
                (workspace, limit),
            ).fetchall()
        return [
            SessionRecord(
                id=r["id"], workspace=r["workspace"], title=r["title"],
                created_at=r["created_at"], updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def delete(self, session_id: str, workspace: str) -> bool:
        """删除会话元数据"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE id = ? AND workspace = ?",
                (session_id, workspace),
            )
            self._conn.commit()
        return cur.rowcount > 0
