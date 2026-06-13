"""AgentBridge — 线程安全的 LangGraph 通信桥梁

在后台线程中运行 LangGraph graph.stream()，通过 asyncio.Queue
将事件安全地传递给 Textual UI 主线程。
"""

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import HumanMessage, AIMessageChunk, SystemMessage
from langgraph.types import Command

from LangCode.shared.logger import get_logger

log = get_logger("tui.bridge")


@dataclass
class BridgeEvent:
    """从 LangGraph 线程传递到 UI 线程的事件"""
    type: str  # "text_chunk" | "tool_call" | "tool_result" | "interrupt" | "done" | "error"
    data: Any = None
    meta: dict = field(default_factory=dict)


class AgentBridge:
    """在后台线程运行 LangGraph，通过异步队列与 TUI 通信"""

    def __init__(self, graph, config: dict, memory_store=None, memory_manager=None,
                 platform_prompt: str = "", agent_prompt: str = ""):
        self.graph = graph
        self.config = config
        self.memory_store = memory_store
        self.memory_manager = memory_manager
        self.platform_prompt = platform_prompt
        self.agent_prompt = agent_prompt
        self._queue: asyncio.Queue[BridgeEvent] = asyncio.Queue(maxsize=500)
        self._interrupt_event = threading.Event()
        self._interrupt_response: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _emit(self, event: BridgeEvent):
        """线程安全的事件发送 — 从后台线程安全地将事件放入异步队列"""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    async def initialize(self):
        """注入系统提示（全新会话时调用）"""
        current_state = self.graph.get_state(self.config)
        is_new = len(current_state.values.get("messages", [])) == 0
        if not is_new:
            return

        init_messages = []
        if self.platform_prompt:
            init_messages.append(SystemMessage(id="platform", content=self.platform_prompt))
        if self.agent_prompt:
            init_messages.append(SystemMessage(id="agent_role", content=self.agent_prompt))
        if init_messages:
            log.info("注入 %d 条系统消息", len(init_messages))
            self.graph.update_state(self.config, {"messages": init_messages})

    async def send_message(self, user_text: str):
        """发送用户消息并异步产出 BridgeEvent"""
        self._loop = asyncio.get_running_loop()

        # 注入记忆上下文
        if self.memory_manager:
            ctx = self.memory_manager.get_context(user_text)
            if ctx:
                log.debug("注入记忆上下文: %d 字符", len(ctx))
                self.graph.update_state(self.config, {"memory_context": ctx})

        log.info("用户输入: %s", user_text[:200])
        thread = threading.Thread(
            target=self._run_stream, args=(user_text,), daemon=True
        )
        thread.start()

        while True:
            event = await self._queue.get()
            if event.type == "interrupt":
                # 等待 UI 获取用户响应后恢复
                self._interrupt_event.clear()
                yield event
                self._interrupt_event.wait()
                self._interrupt_event.clear()  # 重置，确保下一次中断能正常阻塞
                response = self._interrupt_response
                self._interrupt_response = None
                # 在新线程中恢复
                resume_thread = threading.Thread(
                    target=self._resume_stream, args=(response,), daemon=True
                )
                resume_thread.start()
            else:
                yield event
                if event.type in ("done", "error"):
                    break

    def set_interrupt_response(self, response: str):
        """由 UI 线程调用，设置中断响应并唤醒 Agent 线程"""
        self._interrupt_response = response
        self._interrupt_event.set()

    def _run_stream(self, user_text: str):
        """在后台线程中执行 graph.stream()"""
        try:
            events = self.graph.stream(
                {"messages": [HumanMessage(content=user_text)]},
                self.config,
                stream_mode=["messages", "updates"],
            )
            self._process_events(events)
        except Exception as e:
            log.exception("Agent 运行异常")
            self._emit(BridgeEvent("error", str(e)))

    def _resume_stream(self, response: str):
        """在后台线程中恢复被中断的 graph"""
        try:
            log.info("恢复中断，响应: %s", response)
            events = self.graph.stream(
                Command(resume=response), self.config,
                stream_mode=["messages", "updates"],
            )
            self._process_events(events)
        except Exception as e:
            log.exception("恢复中断异常")
            self._emit(BridgeEvent("error", str(e)))

    def _process_events(self, events):
        """处理 LangGraph 事件流，放入队列"""
        _LLM_NODES = {"agent", "synthesize_llm", "report"}
        _TOOL_NODES = {"tools"}

        try:
            for mode, data in events:

                if mode == "messages":
                    chunk, _metadata = data
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        self._emit(
                            BridgeEvent("text_chunk", chunk.content)
                        )

                elif mode == "updates":
                    for key in data:
                        if key in _LLM_NODES:
                            node_msgs = data[key].get("messages")
                            if node_msgs:
                                msgs = node_msgs if isinstance(node_msgs, list) else [node_msgs]
                                for msg in msgs:
                                    for tc in getattr(msg, "tool_calls", []) or []:
                                        self._emit(
                                            BridgeEvent("tool_call", {
                                                "name": tc.get("name", "unknown"),
                                                "args": tc.get("args", {}),
                                            })
                                        )

                        elif key in _TOOL_NODES:
                            for msg in data[key].get("messages", []):
                                name = getattr(msg, "name", "unknown")
                                content = getattr(msg, "content", "")
                                preview = (
                                    content[:800] if isinstance(content, str)
                                    else str(content)[:800]
                                )
                                self._emit(
                                    BridgeEvent("tool_result", {
                                        "name": name,
                                        "content": preview,
                                    })
                                )

                    if "__interrupt__" in data:
                        interrupt_info = data["__interrupt__"]
                        log.info("触发中断: %s", interrupt_info[0].value)
                        self._emit(
                            BridgeEvent("interrupt", interrupt_info[0].value)
                        )
                        # 等待 UI 响应
                        self._interrupt_event.wait()
                        self._interrupt_event.clear()  # 重置，确保下一次中断能正常阻塞
                        return  # 退出当前循环，由 resume_stream 接手

            self._emit(BridgeEvent("done"))

        except Exception as e:
            log.exception("事件处理异常")
            self._emit(BridgeEvent("error", str(e)))
