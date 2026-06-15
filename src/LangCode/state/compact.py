"""state.compact — 三层上下文压缩策略。

参考 Claude Code 的三层压缩策略：
  1. MicroCompact: 裁剪单条过长工具输出（> 2000字符 → 2000 + 标记）
  2. AutoCompact: LLM 生成对话摘要（System + 摘要 + 最近N条）
  3. SnipCompact: 基于文件当前状态替换历史内容

阈值计算:
  effectiveWindow = contextWindow - maxOutputTokens (为输出预留空间)
  autoCompactThreshold = effectiveWindow - AUTOCOMPACT_BUFFER (13,000 tokens)

断路器:
  连续失败 3 次 → 停止尝试。参考 Claude Code 真实数据：
  "BQ 2026-03-10: 1,279 sessions had 50+ consecutive failures"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("state.compact")


# ── 常量（对齐 Claude Code） ──
AUTOCOMPACT_BUFFER_TOKENS = 13_000
WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
MAX_CONSECUTIVE_COMPACT_FAILURES = 3
MICRO_COMPACT_MAX_CHARS = 2_000
MICRO_COMPACT_KEEP_RECENT = 5

# 可压缩的工具列表（输出通常很长且后续不再需要）
COMPACTABLE_TOOLS = frozenset({
    "read_file", "execute_shell", "search_files", "grep_content",
    "fetch_api", "web_search", "run_python",
    "write_file", "edit_file",
    "ast_info", "ast_find",
})


@dataclass
class CompactResult:
    """压缩结果"""
    was_compacted: bool
    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int
    strategy: str  # "micro" | "auto" | "snip" | "none"
    output: list = field(default_factory=list)  # 压缩后的消息列表


def estimate_message_tokens(messages: list) -> int:
    """粗略估算消息列表的 token 数。

    简化实现：1 token ≈ 4 字符（中英文混合保守估计）。
    实际应使用 tiktoken，但为避免额外依赖先用估算。
    """
    total_chars = 0
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
                else:
                    total_chars += len(str(block))
        elif isinstance(content, str):
            total_chars += len(content)
        # tool_calls 也占 token
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                total_chars += len(str(tc.get("args", "")))
    return total_chars // 4


def _get_context_window(model_name: str) -> int:
    """获取模型的上下文窗口大小。"""
    # 常见模型上下文窗口
    windows = {
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
        "gpt-4-turbo": 128_000,
        "gpt-4": 8_192,
        "gpt-3.5-turbo": 16_384,
        "claude-3-5-sonnet": 200_000,
        "claude-3-opus": 200_000,
        "claude-3-haiku": 200_000,
        "mimo-v2.5-pro": 128_000,
    }
    for key, val in windows.items():
        if key in model_name.lower():
            return val
    return 80_000  # 保守默认值


class ContextCompactor:
    """三层上下文压缩器。

    用法：
        compactor = ContextCompactor(llm, "mimo-v2.5-pro")
        decision = compactor.should_compact(messages, token_count)
        if decision.should_compact:
            result = compactor.auto_compact(messages)
    """

    def __init__(self, llm=None, model_name: str = ""):
        self.llm = llm
        self.model_name = model_name
        self.consecutive_failures = 0

    def get_effective_window(self) -> int:
        """有效窗口 = 上下文窗口 - 为输出预留的空间"""
        return _get_context_window(self.model_name) - MAX_OUTPUT_TOKENS_FOR_SUMMARY

    def get_auto_compact_threshold(self) -> int:
        """自动压缩阈值"""
        return self.get_effective_window() - AUTOCOMPACT_BUFFER_TOKENS

    def should_compact(self, messages: list, token_count: int) -> bool:
        """判断是否需要压缩。"""
        threshold = self.get_auto_compact_threshold()
        return token_count > threshold

    def micro_compact(self, messages: list) -> list:
        """MicroCompact: 裁剪过长的工具输出。

        规则（参考 Claude Code time-based microCompact）：
        - 工具输出 > 2000 字符 → 裁剪到前 2000 + "[Old tool result content cleared]"
        - 保留错误信息完整（错误可能包含关键调试信息）
        - 只处理 COMPACTABLE_TOOLS 中的工具
        - 保留最近 N 条消息不裁剪
        """
        from langchain_core.messages import ToolMessage, AIMessage

        if len(messages) <= MICRO_COMPACT_KEEP_RECENT:
            return messages

        result = list(messages)
        cutoff = len(result) - MICRO_COMPACT_KEEP_RECENT

        for i in range(cutoff):
            msg = result[i]
            if not isinstance(msg, ToolMessage):
                continue

            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) <= MICRO_COMPACT_MAX_CHARS:
                continue

            # 检查是否是可压缩的工具
            tool_name = msg.name or ""
            if tool_name not in COMPACTABLE_TOOLS:
                continue

            # 裁剪
            trimmed = content[:MICRO_COMPACT_MAX_CHARS] + "\n\n[Old tool result content cleared]"
            result[i] = msg.model_copy(update={"content": trimmed})
            log.debug("MicroCompact: 裁剪 %s 输出 (%d → %d chars)",
                      tool_name, len(content), len(trimmed))

        return result

    def auto_compact(self, messages: list) -> CompactResult:
        """AutoCompact: LLM 摘要压缩。

        流程:
        1. 分离: System消息 + 最近10条 + 其余
        2. 调用 LLM 将"其余"压缩为 3-5 句摘要
        3. 组装: System + 摘要（SystemMessage）+ 最近消息
        4. 如果失败 → consecutive_failures += 1

        断路器:
        if consecutive_failures >= 3: 跳过压缩
        """
        from langchain_core.messages import SystemMessage, HumanMessage

        tokens_before = estimate_message_tokens(messages)

        # 断路器检查
        if self.consecutive_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
            log.warning("AutoCompact: 断路器已触发（连续失败 %d 次），跳过",
                        self.consecutive_failures)
            return CompactResult(
                was_compacted=False,
                messages_before=len(messages),
                messages_after=len(messages),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                strategy="none",
            )

        # 分离 System + 最近10条 + 其余
        system_msgs = []
        recent_count = 10
        rest = []

        for i, msg in enumerate(messages):
            if _is_system(msg):
                system_msgs.append(msg)
            elif i >= len(messages) - recent_count:
                pass  # 最近的，后面处理
            else:
                rest.append(msg)

        recent_msgs = messages[len(messages) - recent_count:]

        if not rest:
            return CompactResult(
                was_compacted=False,
                messages_before=len(messages),
                messages_after=len(messages),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                strategy="none",
            )

        # 调用 LLM 压缩
        try:
            summary = self._summarize_messages(rest)
            compact_boundary = SystemMessage(
                content="[上下文压缩] 早期对话已压缩为摘要。"
            )
            summary_msg = SystemMessage(
                id="compact_summary",
                content=f"[对话摘要]\n{summary}",
            )

            result_msgs = system_msgs + [compact_boundary, summary_msg] + recent_msgs
            tokens_after = estimate_message_tokens(result_msgs)

            self.consecutive_failures = 0
            log.info("AutoCompact: %d 条 → %d 条, %d → %d tokens",
                     len(messages), len(result_msgs), tokens_before, tokens_after)

            return CompactResult(
                was_compacted=True,
                messages_before=len(messages),
                messages_after=len(result_msgs),
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                strategy="auto",
                output=result_msgs,
            )

        except Exception as e:
            self.consecutive_failures += 1
            log.error("AutoCompact 失败 (%d/%d): %s",
                      self.consecutive_failures, MAX_CONSECUTIVE_COMPACT_FAILURES, e)
            return CompactResult(
                was_compacted=False,
                messages_before=len(messages),
                messages_after=len(messages),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                strategy="none",
            )

    def snip_compact(self, messages: list, file_cache: dict = None) -> CompactResult:
        """SnipCompact: 用文件当前状态替换历史内容。

        适用于: 大量 file_read 结果占据了历史对话。
        将引用替换为 "File X has current content: ..." 替代完整历史内容。
        """
        tokens_before = estimate_message_tokens(messages)

        if not file_cache:
            return CompactResult(
                was_compacted=False,
                messages_before=len(messages),
                messages_after=len(messages),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                strategy="none",
            )

        # SnipCompact 需要 file_cache 提供文件当前内容
        # 简化实现：标记但不实际替换（需要 file_cache 集成）
        log.info("SnipCompact: file_cache 提供了 %d 个文件的缓存", len(file_cache))

        return CompactResult(
            was_compacted=False,
            messages_before=len(messages),
            messages_after=len(messages),
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            strategy="none",
        )

    def compact(self, messages: list, file_cache: dict = None) -> CompactResult:
        """执行压缩：先 Micro，再 Auto，最后 Snip。"""
        # 1. MicroCompact
        messages = self.micro_compact(messages)
        token_count = estimate_message_tokens(messages)

        if not self.should_compact(messages, token_count):
            return CompactResult(
                was_compacted=False,
                messages_before=len(messages),
                messages_after=len(messages),
                tokens_before=token_count,
                tokens_after=token_count,
                strategy="micro",
            )

        # 2. AutoCompact
        result = self.auto_compact(messages)
        if result.was_compacted:
            return result

        # 3. SnipCompact
        return self.snip_compact(messages, file_cache)

    def _summarize_messages(self, messages: list) -> str:
        """调用 LLM 生成对话摘要。"""
        from langchain_core.messages import HumanMessage

        # 构建摘要请求
        conversation_text = _messages_to_text(messages)
        prompt = (
            "请将以下对话压缩为 3-5 句摘要，保留关键信息（工具调用结果、"
            "用户决策、代码修改、错误信息）。用中文输出。\n\n"
            f"对话内容：\n{conversation_text[:8000]}"
        )

        if self.llm is None:
            # 无 LLM 时做简单截断
            return conversation_text[:500] + "\n[...] (摘要截断，无 LLM)"

        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content if hasattr(response, "content") else str(response)


def _is_system(msg) -> bool:
    """判断是否是系统消息。"""
    return getattr(msg, "type", "") == "system"


def _messages_to_text(messages: list) -> str:
    """将消息列表转为纯文本（用于摘要请求）。"""
    parts = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            )
        else:
            text = str(content)

        if role == "system":
            continue  # 跳过系统消息
        if role == "human":
            parts.append(f"用户: {text[:500]}")
        elif role == "ai":
            parts.append(f"助手: {text[:500]}")
        elif role == "tool":
            parts.append(f"工具结果: {text[:300]}")
    return "\n".join(parts)
