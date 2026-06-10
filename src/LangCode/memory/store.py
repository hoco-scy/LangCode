"""基于 SQLite + FTS5 的持久化记忆存储"""

import sqlite3
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from LangCode.shared.logger import get_logger

log = get_logger("memory.store")


class MemoryRecord(BaseModel):
    """单条记忆记录"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = Field(description="记忆内容")
    memory_type: str = Field(description="记忆类型: fact/preference/project/skill")
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = Field(default=0)


class SQLiteMemoryStore:
    """SQLite + FTS5 持久化记忆存储，支持全文搜索"""

    def __init__(self, db_path: str = str(Path.home() / ".langcode" / "memory.db")):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()
        log.info("MemoryStore 初始化: %s", self.db_path)

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                id UNINDEXED,
                content,
                memory_type UNINDEXED,
                tags,
                content='memories',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, id, content, memory_type, tags)
                VALUES (new.rowid, new.id, new.content, new.memory_type, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, id, content, memory_type, tags)
                VALUES ('delete', old.rowid, old.id, old.content, old.memory_type, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, id, content, memory_type, tags)
                VALUES ('delete', old.rowid, old.id, old.content, old.memory_type, old.tags);
                INSERT INTO memories_fts(rowid, id, content, memory_type, tags)
                VALUES (new.rowid, new.id, new.content, new.memory_type, new.tags);
            END;
        """)
        self._conn.commit()

    def save(self, record: MemoryRecord) -> str:
        """保存一条记忆，返回 ID"""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO memories (id, content, memory_type, tags, created_at, access_count) VALUES (?, ?, ?, ?, ?, ?)",
                (record.id, record.content, record.memory_type, json.dumps(record.tags, ensure_ascii=False), record.created_at, record.access_count)
            )
            self._conn.commit()
        log.debug("记忆已保存: id=%s type=%s", record.id, record.memory_type)
        return record.id

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        """全文搜索记忆。FTS5 不支持 CJK 分词，空结果时自动降级为 LIKE"""
        with self._lock:
            rows = []
            try:
                cursor = self._conn.execute(
                    """SELECT m.id, m.content, m.memory_type, m.tags, m.created_at, m.access_count
                       FROM memories_fts f
                       JOIN memories m ON f.id = m.id
                       WHERE memories_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, top_k)
                )
                rows = cursor.fetchall()
            except Exception:
                log.debug("FTS 语法错误，降级为 LIKE 搜索")

            if not rows:
                cursor = self._conn.execute(
                    """SELECT id, content, memory_type, tags, created_at, access_count
                       FROM memories WHERE content LIKE ? LIMIT ?""",
                    (f"%{query}%", top_k)
                )
                rows = cursor.fetchall()

            results = []
            for row in rows:
                self._conn.execute("UPDATE memories SET access_count = access_count + 1 WHERE id = ?", (row["id"],))
                results.append(MemoryRecord(
                    id=row["id"],
                    content=row["content"],
                    memory_type=row["memory_type"],
                    tags=json.loads(row["tags"]),
                    created_at=row["created_at"],
                    access_count=row["access_count"] + 1,
                ))
            self._conn.commit()
        log.debug("搜索 '%s' 找到 %d 条记忆", query, len(results))
        return results

    def list_all(self, memory_type: Optional[str] = None, limit: int = 50) -> list[MemoryRecord]:
        """列出所有记忆，可按类型过滤"""
        with self._lock:
            if memory_type:
                cursor = self._conn.execute(
                    "SELECT id, content, memory_type, tags, created_at, access_count FROM memories WHERE memory_type = ? ORDER BY created_at DESC LIMIT ?",
                    (memory_type, limit)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT id, content, memory_type, tags, created_at, access_count FROM memories ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            rows = cursor.fetchall()
        return [MemoryRecord(
            id=row["id"], content=row["content"], memory_type=row["memory_type"],
            tags=json.loads(row["tags"]), created_at=row["created_at"], access_count=row["access_count"]
        ) for row in rows]

    def delete(self, memory_id: str) -> bool:
        """删除一条记忆"""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
            deleted = cursor.rowcount > 0
        log.debug("删除记忆 %s: %s", memory_id, "成功" if deleted else "不存在")
        return deleted

    def count(self) -> int:
        """返回记忆总数"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
        return row["cnt"]
