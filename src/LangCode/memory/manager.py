"""记忆管理器：负责自动提取、检索和上下文注入"""

from typing import Optional
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from LangCode.memory.store import SQLiteMemoryStore, MemoryRecord
from LangCode.shared.logger import get_logger

log = get_logger("memory.manager")

# 自动提取记忆的提示词
AUTO_EXTRACT_PROMPT = """分析以下对话，判断是否有值得长期记忆的信息。

值得记忆的信息包括：
- 用户的偏好（如编程语言、代码风格、工作习惯）
- 项目相关的决策或约束
- 用户明确要求记住的内容
- 重要的技术事实或经验

不值得记忆的信息：
- 一次性的工具调用结果
- 临时的调试信息
- 通用知识（如 Python 语法）

如果值得记忆，返回 JSON 数组（每条包含 content 和 memory_type）：
[{{"content": "...", "memory_type": "fact|preference|project|skill", "tags": ["tag1"]}}]

如果没有值得记忆的内容，返回空数组：[]

只返回 JSON，不要解释。

对话内容：
{conversation}
"""


class MemoryManager:
    """记忆管理器"""

    def __init__(self, store: SQLiteMemoryStore, llm: Optional[ChatOpenAI] = None):
        self.store = store
        self.llm = llm
        log.info("MemoryManager 初始化, store=%s", store.db_path)

    def get_context(self, query: str, top_k: int = 5) -> str:
        """根据查询检索相关记忆，返回拼接好的上下文字符串"""
        records = self.store.search(query, top_k=top_k)
        if not records:
            return ""
        lines = []
        for r in records:
            tags_str = f" [{', '.join(r.tags)}]" if r.tags else ""
            lines.append(f"- ({r.memory_type}{tags_str}) {r.content}")
        context = "\n".join(lines)
        log.debug("注入记忆上下文: %d 条", len(records))
        return context

    def auto_save(self, messages: list[BaseMessage]) -> list[str]:
        """从对话中自动提取值得记忆的信息并保存，返回保存的 ID 列表"""
        if not self.llm:
            log.warning("auto_save 跳过: LLM 未配置")
            return []

        # 只取最近几轮对话
        recent = messages[-10:]
        conversation = "\n".join(
            f"{'用户' if m.type == 'human' else '助手' if m.type == 'ai' else m.type}: {m.content}"
            for m in recent
            if hasattr(m, 'content') and m.content
        )

        if len(conversation) < 50:
            return []

        try:
            prompt = AUTO_EXTRACT_PROMPT.format(conversation=conversation)
            response = self.llm.invoke(prompt)
            content = response.content.strip()

            # 解析 JSON
            import json
            # 处理可能的 markdown 代码块
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            items = json.loads(content)
            if not isinstance(items, list):
                return []

            saved_ids = []
            for item in items:
                if not isinstance(item, dict) or "content" not in item:
                    continue
                record = MemoryRecord(
                    content=item["content"],
                    memory_type=item.get("memory_type", "fact"),
                    tags=item.get("tags", []),
                )
                rid = self.store.save(record)
                saved_ids.append(rid)
                log.info("自动保存记忆: id=%s type=%s", rid, record.memory_type)

            return saved_ids
        except Exception as e:
            log.warning("auto_save 解析失败: %s", e)
            return []

    def summarize_for_injection(self, query: str, max_chars: int = 2000) -> str:
        """获取记忆上下文，截断到指定长度，用于注入系统提示"""
        context = self.get_context(query)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n...(记忆已截断)"
        return context
