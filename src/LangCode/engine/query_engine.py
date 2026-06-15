"""QueryEngine — 会话生命周期管理器。

参考 Claude Code QueryEngine 设计：
- 一个对话一个实例
- submit_message() 封装完整的图执行生命周期
- 流式输出：AsyncGenerator[EngineEvent]

LangCode 特殊性：
- LangGraph StateGraph 已提供图执行和 checkpoint 持久化
- QueryEngine 主要负责：初始化、事件分类、异常恢复、结果汇总
- 不需要重写 query_loop（LangGraph 的 graph.stream() 已是完整状态机）
"""

from __future__ import annotations

import time
import uuid
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional, Any
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, AIMessageChunk, SystemMessage, AIMessage
from langgraph.types import Command

from LangCode.shared.logger import get_logger

log = get_logger("engine.query_engine")


@dataclass
class EngineEvent:
    """引擎事件（统一的输出格式）

    type:
      - "text_chunk": LLM 流式文本片段
      - "tool_call": 工具调用（name + args）
      - "tool_result": 工具执行结果（name + content）
      - "route": 路由决策（explore/review/plan/react）
      - "plan": 计划事件（mark_step/reflector）
      - "verify": 验证事件（pass/fail）
      - "interrupt": 中断（需用户确认）
      - "error": 错误
      - "done": 轮次完成
    """
    type: str
    data: Any = None
    meta: dict = field(default_factory=dict)


@dataclass
class QueryEngineConfig:
    """查询引擎配置"""
    workspace_dir: str
    graph: Any                              # LangGraph CompiledStateGraph
    config: dict                            # {"configurable": {"thread_id": ...}}
    agent_prompt: str = ""
    platform_prompt: str = ""
    memory_store: Any = None
    memory_manager: Any = None
    session_store: Any = None
    current_session: Any = None
    tool_registry: Any = None               # ToolRegistry
    rule_engine: Any = None                 # RuleEngine
    path_sandbox: Any = None                # PathSandbox
    tool_context: Any = None                # ToolUseContext
    analytics: Any = None                   # AnalyticsTracker
    transcript: Any = None                  # TranscriptWriter（JSONL 持久化）


class QueryEngine:
    """查询引擎：管理一个完整对话会话。

    用法：
        engine = QueryEngine(config)
        async for event in engine.submit_message("帮我读 main.py"):
            if event.type == "text_chunk":
                print(event.data, end="")
            elif event.type == "done":
                print("完成")
    """

    def __init__(self, engine_config: QueryEngineConfig):
        self.cfg = engine_config
        self.graph = engine_config.graph
        self.config = engine_config.config
        self._initialized = False

    def _ensure_initialized(self):
        """首次调用时注入系统提示词"""
        if self._initialized:
            return
        self._initialized = True

        current_state = self.graph.get_state(self.config)
        is_new = len(current_state.values.get("messages", [])) == 0

        if is_new:
            init_messages = []
            if self.cfg.platform_prompt:
                init_messages.append(SystemMessage(id="platform", content=self.cfg.platform_prompt))
            if self.cfg.agent_prompt:
                init_messages.append(SystemMessage(id="agent_role", content=self.cfg.agent_prompt))
            if init_messages:
                self.graph.update_state(self.config, {"messages": init_messages})
            if self.cfg.session_store and self.cfg.current_session:
                self.cfg.session_store.save(self.cfg.current_session)

    def submit_message(self, prompt: str) -> AsyncGenerator[EngineEvent, None]:
        """提交用户消息，流式返回引擎事件。

        这是同步生成器（LangGraph 的 graph.stream() 是同步的），
        CLI 的 consume_events 直接遍历即可。

        流程：
        1. 注入记忆上下文
        2. 调用 graph.stream()
        3. 分类事件并 yield
        4. 处理中断恢复
        """
        import asyncio

        self._ensure_initialized()

        # 注入记忆上下文
        if self.cfg.memory_manager:
            ctx = self.cfg.memory_manager.get_context(prompt)
            if ctx:
                self.graph.update_state(self.config, {"memory_context": ctx})

        # 发送用户消息
        log.info("用户输入: %s", prompt[:200])
        user_msg = HumanMessage(content=prompt)

        # Transcript 持久化（崩溃安全）
        if self.cfg.transcript:
            self.cfg.transcript.append(user_msg)

        events = self.graph.stream(
            {"messages": [user_msg]},
            self.config,
            stream_mode=["messages", "updates"],
        )

        yield from self._consume_events(events)

        # Transcript 持久化：将本轮 AI 响应写入 JSONL
        if self.cfg.transcript:
            current_state = self.graph.get_state(self.config)
            all_msgs = current_state.values.get("messages", [])
            for msg in all_msgs[-10:]:
                msg_type = getattr(msg, "type", "")
                if msg_type in ("ai", "system", "tool"):
                    self.cfg.transcript.append(msg)

    def resume_after_interrupt(self, user_response: str) -> AsyncGenerator[EngineEvent, None]:
        """中断恢复"""
        events = self.graph.stream(
            Command(resume=user_response), self.config,
            stream_mode=["messages", "updates"],
        )
        yield from self._consume_events(events)

    def _consume_events(self, events) -> AsyncGenerator[EngineEvent, None]:
        """消费 LangGraph 事件流，转换为 EngineEvent。

        节点分类（对齐 LangCode v2 的图结构）：
        - LLM 节点: agent, summarize_llm, report
        - 工具节点: tools
        - 路由节点: router (process_tool_results)
        - 计划节点: mark_step, reflector
        - 验证节点: auto_verify
        """
        _LLM_NODES = {"agent", "summarize_llm", "report"}
        _TOOL_NODES = {"tools"}
        _ROUTE_NODES = {"router"}
        _PLAN_NODES = {"mark_step", "reflector"}
        _VERIFY_NODES = {"auto_verify"}

        interrupted = False

        try:
            for mode, data in events:
                if mode == "messages":
                    chunk, _metadata = data
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield EngineEvent(type="text_chunk", data=chunk.content)

                elif mode == "updates":
                    for key in data:
                        node_data = data[key]
                        if node_data is None:
                            continue

                        if key in _LLM_NODES:
                            node_msgs = node_data.get("messages")
                            if node_msgs:
                                msgs = node_msgs if isinstance(node_msgs, list) else [node_msgs]
                                for msg in msgs:
                                    for tc in getattr(msg, "tool_calls", []) or []:
                                        yield EngineEvent(
                                            type="tool_call",
                                            data={"name": tc["name"], "args": tc.get("args", {})},
                                        )

                        elif key in _TOOL_NODES:
                            for msg in node_data.get("messages", []):
                                tool_name = getattr(msg, "name", "unknown")
                                content = getattr(msg, "content", "")
                                preview = content[:500] if isinstance(content, str) else str(content)[:500]
                                yield EngineEvent(
                                    type="tool_result",
                                    data={"name": tool_name, "content": preview},
                                )

                        elif key in _ROUTE_NODES:
                            route = node_data.get("route", "")
                            if route:
                                yield EngineEvent(type="route", data=route)

                        elif key in _PLAN_NODES:
                            yield EngineEvent(type="plan", data={"node": key})

                        elif key in _VERIFY_NODES:
                            verify_errors = node_data.get("verify_errors")
                            if verify_errors:
                                yield EngineEvent(type="verify", data={"status": "fail", "errors": verify_errors})
                            else:
                                yield EngineEvent(type="verify", data={"status": "pass"})

                    if "__interrupt__" in data:
                        interrupt_info = data["__interrupt__"]
                        yield EngineEvent(type="interrupt", data=interrupt_info[0].value)
                        return  # 由 resume_after_interrupt 接管

            yield EngineEvent(type="done")

        except Exception as e:
            log.error("事件流异常: %s", e)
            yield EngineEvent(type="error", data=str(e))

    def get_current_state(self) -> dict:
        """获取当前图状态"""
        return self.graph.get_state(self.config).values

    def update_state(self, updates: dict):
        """更新图状态"""
        self.graph.update_state(self.config, updates)
