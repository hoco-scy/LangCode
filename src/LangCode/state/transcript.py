"""state/transcript — JSONL 只追加日志的会话持久化。

参考 Claude Code transcript 机制：
- 只追加写入 (append-only)，崩溃安全。JSONL 格式保证即使进程崩溃也不损坏已有数据。
- parent_uuid 字段形成消息链，支持分支会话（sidechain）。
- 恢复时从最新叶节点沿 parent_uuid 回溯重建主链。
- 每 session 一个 JSONL 文件。

路径: ~/.langcode/sessions/{session_id}.jsonl

与 SessionStore 的关系:
  SessionStore: 会话元数据索引（id, workspace, title, timestamps）— 供 /session 命令查询
  Transcript:   消息全文（JSONL）+ 崩溃恢复 + 跨会话搜索
"""

from __future__ import annotations

import json
import uuid
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("state.transcript")

SESSIONS_DIR = Path.home() / ".langcode" / "sessions"


def _message_to_dict(message) -> dict:
    """将 LangChain 消息转为可序列化的 dict。"""
    msg_type = getattr(message, "type", "unknown")
    content = message.content if hasattr(message, "content") else ""

    result = {
        "type": msg_type,
        "content": content,
    }

    # AIMessage tool_calls
    if hasattr(message, "tool_calls") and message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
            for tc in message.tool_calls
        ]

    # ToolMessage 特殊字段
    if msg_type == "tool":
        result["tool_call_id"] = getattr(message, "tool_call_id", "")
        result["name"] = getattr(message, "name", "")

    # message id
    if hasattr(message, "id") and message.id:
        result["msg_id"] = message.id

    return result


def _dict_to_message(d: dict):
    """从 dict 恢复 LangChain 消息。"""
    from langchain_core.messages import (
        HumanMessage, AIMessage, SystemMessage, ToolMessage,
    )

    msg_type = d.get("type", "unknown")
    content = d.get("content", "")
    msg_id = d.get("msg_id", "")

    if msg_type == "human":
        return HumanMessage(content=content, id=msg_id)
    elif msg_type == "system":
        return SystemMessage(content=content, id=msg_id)
    elif msg_type == "ai":
        tool_calls = d.get("tool_calls", [])
        return AIMessage(content=content, id=msg_id, tool_calls=tool_calls)
    elif msg_type == "tool":
        return ToolMessage(
            content=content,
            tool_call_id=d.get("tool_call_id", ""),
            name=d.get("name", ""),
            id=msg_id,
        )
    else:
        # 未知类型 → HumanMessage 兜底
        return HumanMessage(content=content, id=msg_id)


class TranscriptWriter:
    """JSONL 只追加写入器 — 崩溃安全的消息持久化。

    用法:
        writer = TranscriptWriter(session_id="abc123")
        parent = None
        parent = writer.append(HumanMessage(content="hi"), parent)
        parent = writer.append(AIMessage(content="hello"), parent)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.file_path = SESSIONS_DIR / f"{session_id}.jsonl"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_uuid: Optional[str] = None

    def append(self, message, parent_uuid: Optional[str] = None) -> str:
        """追加一条消息到 JSONL 文件。

        Args:
            message: LangChain 消息对象
            parent_uuid: 父消息 UUID（None 则使用上次追加的 UUID）

        Returns:
            新生成的消息 UUID
        """
        msg_uuid = uuid.uuid4().hex[:12]
        parent = parent_uuid or self._last_uuid

        record = {
            "uuid": msg_uuid,
            "parent_uuid": parent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "message": _message_to_dict(message),
        }

        line = json.dumps(record, ensure_ascii=False)

        with self._lock:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            self._last_uuid = msg_uuid

        log.debug("Transcript 写入: uuid=%s parent=%s type=%s",
                  msg_uuid, parent, getattr(message, "type", "?"))
        return msg_uuid

    def get_last_uuid(self) -> Optional[str]:
        """获取最后写入的 UUID。"""
        return self._last_uuid


class TranscriptReader:
    """从 JSONL 文件恢复会话消息。

    恢复策略:
      1. 读取所有行，按 uuid 索引
      2. 找到最新叶节点（无子节点的节点）
      3. 沿 parent_uuid 回溯重建主链
      4. 按链顺序返回消息列表
    """

    def load(self, session_id: str) -> list:
        """恢复会话消息列表。

        Returns:
            LangChain 消息列表（按时间顺序）
        """
        file_path = SESSIONS_DIR / f"{session_id}.jsonl"
        if not file_path.exists():
            return []

        records = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("跳过损坏行: %s", line[:100])

        if not records:
            return []

        # 构建 uuid → record 索引
        by_uuid = {r["uuid"]: r for r in records}

        # 找到叶节点：存在于 records 但没有其他 record 指向它的 uuid
        children = {r.get("parent_uuid") for r in records if r.get("parent_uuid")}
        leaf_candidates = [r for r in records if r["uuid"] not in children]

        if not leaf_candidates:
            # 无叶节点（理论上不应发生）→ 返回全部
            return [_dict_to_message(r["message"]) for r in records]

        # 取最新叶节点（按 timestamp 排序）
        leaf = max(leaf_candidates, key=lambda r: r.get("timestamp", ""))

        # 沿 parent_uuid 回溯重建主链
        chain = []
        current = leaf
        visited = set()
        while current:
            if current["uuid"] in visited:
                break
            visited.add(current["uuid"])
            chain.append(current)
            parent_uuid = current.get("parent_uuid")
            current = by_uuid.get(parent_uuid) if parent_uuid else None

        chain.reverse()
        return [_dict_to_message(r["message"]) for r in chain]

    def list_sessions(self, limit: int = 20) -> list[SessionMeta]:
        """列出所有会话（按最后修改时间倒序）。"""
        if not SESSIONS_DIR.exists():
            return []

        sessions = []
        for f in SESSIONS_DIR.glob("*.jsonl"):
            session_id = f.stem
            stat = f.stat()
            # 读取第一行提取首条用户消息作为标题
            title = "新对话"
            msg_count = 0
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        msg_count += 1
                        if msg_count == 1:
                            rec = json.loads(line)
                            msg = rec.get("message", {})
                            if msg.get("type") == "human":
                                title = msg.get("content", "")[:60]
            except Exception:
                pass

            sessions.append(SessionMeta(
                id=session_id,
                title=title or "新对话",
                message_count=msg_count,
                created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            ))

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    def delete(self, session_id: str) -> bool:
        """删除会话 JSONL 文件。"""
        file_path = SESSIONS_DIR / f"{session_id}.jsonl"
        if file_path.exists():
            file_path.unlink()
            log.info("Transcript 删除: %s", session_id)
            return True
        return False


class SessionMeta:
    """会话元数据（用于列表展示）"""

    def __init__(
        self,
        id: str,
        title: str = "新对话",
        message_count: int = 0,
        created_at: str = "",
        updated_at: str = "",
    ):
        self.id = id
        self.title = title
        self.message_count = message_count
        self.created_at = created_at
        self.updated_at = updated_at
