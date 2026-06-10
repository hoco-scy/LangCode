"""上下文窗口管理：Token 计数 + 消息裁剪 + 对话摘要

解决长对话撑爆 LLM 上下文窗口的问题。
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from LangCode.shared.logger import get_logger

log = get_logger("context")

# 默认上下文窗口大小（tokens），留出输出空间
DEFAULT_MAX_TOKENS = 80_000
# 保留最近 N 条消息不做裁剪
KEEP_RECENT = 10
# 摘要触发阈值：超过 max_tokens 的比例时触发摘要
SUMMARY_THRESHOLD = 0.85


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量

    使用简单的字符比例估算：
    - 英文：约 1 token / 4 字符
    - 中文：约 1 token / 2 字符
    - 混合文本取中间值
    """
    if not text:
        return 0
    # 计算中文字符比例
    cjk_chars = sum(1 for c in text if '一' <= c <= '鿿')
    total_chars = len(text)
    if total_chars == 0:
        return 0
    cjk_ratio = cjk_chars / total_chars
    # 中文 token 率约 0.5，英文约 0.25，按比例混合
    chars_per_token = 2 * cjk_ratio + 4 * (1 - cjk_ratio)
    return max(1, int(total_chars / chars_per_token))


def count_message_tokens(message: BaseMessage) -> int:
    """估算单条消息的 token 数"""
    content = message.content if isinstance(message.content, str) else str(message.content)
    # 额外 token 开销（role、格式等）
    return estimate_tokens(content) + 4


def count_messages_tokens(messages: list[BaseMessage]) -> int:
    """估算消息列表的总 token 数"""
    return sum(count_message_tokens(m) for m in messages)


def trim_messages(messages: list[BaseMessage], max_tokens: int = DEFAULT_MAX_TOKENS) -> list[BaseMessage]:
    """滑动窗口裁剪：保留系统消息 + 最近的消息，裁剪中间的旧消息

    策略：
    1. 始终保留所有 SystemMessage（系统提示、记忆上下文等）
    2. 保留最近 KEEP_RECENT 条非系统消息
    3. 如果总 token 仍超限，从最旧的非系统消息开始裁剪
    4. 在裁剪处插入一条摘要消息说明发生了裁剪
    """
    total = count_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    log.info("上下文裁剪: %d tokens > %d 限制", total, max_tokens)

    # 分离系统消息和非系统消息
    system_msgs = []
    non_system = []
    for i, m in enumerate(messages):
        if isinstance(m, SystemMessage):
            system_msgs.append((i, m))
        else:
            non_system.append((i, m))

    # 始终保留最近的非系统消息
    keep_count = min(KEEP_RECENT, len(non_system))
    recent = non_system[-keep_count:] if keep_count > 0 else []
    old = non_system[:-keep_count] if keep_count < len(non_system) else []

    # 计算保留消息的 token 数
    kept_msgs = [m for _, m in system_msgs] + [m for _, m in recent]
    kept_tokens = count_messages_tokens(kept_msgs)

    if kept_tokens > max_tokens:
        # 仍然超限，减少保留的最近消息数量
        while recent and kept_tokens > max_tokens:
            removed = recent.pop(0)
            kept_tokens -= count_message_tokens(removed[1])
        log.warning("上下文严重超限，已减少保留的最近消息数")

    # 构建裁剪后的消息列表
    result = [m for _, m in system_msgs]

    if old:
        # 插入裁剪标记
        trimmed_count = len(old)
        trim_notice = SystemMessage(
            id="context_trim",
            content=f"[上下文管理] 已裁剪 {trimmed_count} 条早期对话消息以控制上下文长度。"
                    f"被裁剪的消息涵盖对话的早期部分，最近的对话内容已保留。"
        )
        result.append(trim_notice)

    result.extend(m for _, m in recent)

    final_tokens = count_messages_tokens(result)
    log.info("裁剪完成: %d -> %d tokens (%d 条消息)", total, final_tokens, len(result))
    return result


def summarize_old_messages(
    messages: list[BaseMessage],
    llm,
    keep_recent: int = KEEP_RECENT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[BaseMessage]:
    """使用 LLM 将旧消息压缩为摘要，保留最近的消息原文

    仅在总 token 超过阈值时触发摘要。
    """
    total = count_messages_tokens(messages)
    if total <= max_tokens * SUMMARY_THRESHOLD:
        return messages

    log.info("触发对话摘要: %d tokens > %d 阈值", total, int(max_tokens * SUMMARY_THRESHOLD))

    # 分离系统消息和非系统消息
    system_msgs = []
    non_system = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system_msgs.append(m)
        else:
            non_system.append(m)

    if len(non_system) <= keep_recent:
        return messages

    old_messages = non_system[:-keep_recent]
    recent_messages = non_system[-keep_recent:]

    # 构建摘要请求
    conversation_text = []
    for m in old_messages:
        role = "用户" if isinstance(m, HumanMessage) else "助手"
        content = m.content if isinstance(m.content, str) else str(m.content)
        conversation_text.append(f"{role}: {content[:500]}")

    summary_prompt = f"""请将以下对话压缩为简洁的摘要，保留关键信息（用户需求、做出的决策、重要结论）。
对话内容：
{chr(10).join(conversation_text)}

请用 3-5 句话概括以上对话的要点："""

    try:
        response = llm.invoke([HumanMessage(content=summary_prompt)])
        summary = response.content if isinstance(response.content, str) else str(response.content)
        log.info("对话摘要完成: %d 条消息 -> 摘要 (%d 字符)", len(old_messages), len(summary))
    except Exception as e:
        log.warning("对话摘要失败: %s，回退到裁剪", e)
        return trim_messages(messages, max_tokens)

    # 组装：系统消息 + 摘要 + 最近消息
    result = list(system_msgs)
    result.append(SystemMessage(
        id="conversation_summary",
        content=f"[对话摘要]\n{summary}"
    ))
    result.extend(recent_messages)

    final_tokens = count_messages_tokens(result)
    log.info("摘要后: %d -> %d tokens", total, final_tokens)
    return result
