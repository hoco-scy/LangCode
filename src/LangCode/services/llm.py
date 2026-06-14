"""LLMClient — 模型管理、thinking签名剥离、动态工具绑定。

参考 Claude Code services/api/ 的设计思路：
- 模型切换: 主模型 → fallback 自动降级
- thinking 签名剥离: 降级到不支持 thinking 的模型时需要
- 动态工具绑定: 每次 _call_llm 时根据 agent_mode 绑定工具子集

关键设计：
  主模型和 fallback 模型都是 ChatOpenAI 实例。
  降级时交换 primary ↔ fallback，不修改已创建的实例。
  thinking 签名剥离防止 "replaying a protected-thinking block
  to an unprotected fallback 400s" 的错误。
"""

from __future__ import annotations

from typing import Any, Optional, Type

from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk

from LangCode.services.config import Config
from LangCode.shared.logger import get_logger

log = get_logger("services.llm")


class LLMClient:
    """LLM 客户端封装。

    用法：
        config = Config.load(workspace_dir)
        llm_client = LLMClient(config)
        bound = llm_client.bind_tools([tool1, tool2])
        response = bound.invoke(messages)
    """

    def __init__(self, config: Config):
        model_cfg = config.get_model()

        self.primary_model = ChatOpenAI(
            model=model_cfg["name"],
            api_key=model_cfg["api_key"] or None,
            base_url=model_cfg["base_url"] or None,
            temperature=model_cfg["temperature"],
        )

        self.fallback_model: Optional[ChatOpenAI] = None
        fallback_name = model_cfg.get("fallback", "")
        if fallback_name:
            self.fallback_model = ChatOpenAI(
                model=fallback_name,
                api_key=model_cfg["api_key"] or None,
                base_url=model_cfg["base_url"] or None,
                temperature=0,
            )
            log.info("已配置 fallback 模型: %s", fallback_name)

        log.info("LLMClient 初始化: model=%s base_url=%s",
                 model_cfg["name"], model_cfg["base_url"])

    @property
    def model_name(self) -> str:
        """当前主模型名称。"""
        return self.primary_model.model_name

    def bind_tools(self, tools: list[BaseTool]) -> ChatOpenAI:
        """动态绑定工具。

        每次 Supervisor._call_llm 调用，根据 agent_mode 过滤后绑定。
        LLM 只看到它有权限使用的工具 → 从源头避免越权调用。

        Args:
            tools: 经过权限过滤后的工具列表

        Returns:
            绑定了工具的 ChatOpenAI 实例
        """
        return self.primary_model.bind_tools(tools)

    def bind_structured_output(self, schema: Any) -> ChatOpenAI:
        """绑定结构化输出（用于 Reflector 等节点的 Pydantic schema）。

        Args:
            schema: Pydantic BaseModel 子类

        Returns:
            绑定了 schema 的 ChatOpenAI 实例
        """
        return self.primary_model.with_structured_output(schema)

    def switch_to_fallback(self) -> bool:
        """切换到 fallback 模型。

        Returns:
            是否成功切换（如果没有 fallback 则返回 False）
        """
        if not self.fallback_model:
            return False
        self.primary_model, self.fallback_model = self.fallback_model, self.primary_model
        log.warning("已切换到 fallback 模型: %s", self.primary_model.model_name)
        return True

    def strip_thinking_signatures(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """剥离 protected thinking blocks。

        当降级到不支持 thinking 的模型时，需要剥离 protected thinking blocks。
        参考 Claude Code query.ts: "Thinking signatures are model-bound:
        replaying a protected-thinking block to an unprotected fallback 400s."

        简化实现：如果消息中有 thinking 块，替换为普通文本块。
        """
        result: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, (AIMessage, AIMessageChunk)):
                if isinstance(msg.content, list):
                    cleaned_content = []
                    for block in msg.content:
                        if isinstance(block, dict) and block.get("type") == "thinking":
                            # 跳过 thinking 块（降级模型不支持）
                            continue
                        cleaned_content.append(block)
                    result.append(msg.model_copy(update={"content": cleaned_content}))
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result
