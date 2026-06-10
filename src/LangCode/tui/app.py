"""LangCode TUI — 基于 Textual 的终端用户界面"""

import asyncio
from datetime import datetime

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Footer, Header, Input, Label, RichLog, Static,
)
from textual.binding import Binding

from LangCode.tui.bridge import AgentBridge
from LangCode.shared.logger import get_logger

log = get_logger("tui.app")

# ── 样式常量 ──────────────────────────────────────────────
AGENT_COLOR = "#4ECDC4"
USER_COLOR = "#FF6B6B"
TOOL_COLOR = "#FFD93D"
DIM_COLOR = "#7C7C7C"
ERROR_COLOR = "#FF4444"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── 中断确认弹窗 ──────────────────────────────────────────

class InterruptModal(ModalScreen[str]):
    """当 Agent 触发 interrupt() 时弹出的确认对话框"""

    def __init__(self, question: str, **kwargs):
        super().__init__(**kwargs)
        self.question = question

    def compose(self) -> ComposeResult:
        with Container(id="interrupt-dialog"):
            yield Label("Agent 需要确认", classes="dialog-title")
            yield Static(self.question, classes="dialog-body")
            with Horizontal(id="interrupt-buttons"):
                yield Button("确认", variant="primary", id="btn-ok")
                yield Button("跳过", variant="default", id="btn-skip")
                yield Button("取消", variant="error", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def _on_ok(self):
        self.dismiss("ok")

    @on(Button.Pressed, "#btn-skip")
    def _on_skip(self):
        self.dismiss("skip")

    @on(Button.Pressed, "#btn-cancel")
    def _on_cancel(self):
        self.dismiss("cancel")


# ── 主应用 ────────────────────────────────────────────────

class LangCodeTUI(App):
    """LangCode 的终端用户界面"""

    TITLE = "LangCode Agent"
    SUB_TITLE = "基于 LangGraph 的多 Agent 协作系统"

    CSS = """
    Header {
        background: $panel;
        color: $text;
    }

    #chat-area {
        background: $surface;
        padding: 1 2;
    }

    #chat-log {
        height: 1fr;
    }

    #streaming-text {
        color: #4ECDC4;
        padding: 0 1;
        height: auto;
        min-height: 1;
    }

    #streaming-text.hidden {
        display: none;
    }

    #input-area {
        background: $panel;
        padding: 1 2;
        height: auto;
        border-top: solid $primary;
    }

    #prompt {
        dock: left;
        color: $accent;
        margin-right: 1;
    }

    #user-input {
        width: 1fr;
    }

    Footer {
        background: $panel;
    }

    #interrupt-dialog {
        background: $panel;
        border: thick $accent;
        padding: 1 2;
        width: 60;
        height: auto;
        margin: 5 10;
    }

    .dialog-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }

    .dialog-body {
        padding: 1 0;
        margin-bottom: 1;
    }

    #interrupt-buttons {
        align: right middle;
    }

    #interrupt-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+m", "show_memory", "查看记忆"),
        Binding("ctrl+l", "clear_screen", "清屏"),
        Binding("escape", "cancel_stream", "取消"),
    ]

    def __init__(self, graph, config, memory_store=None, memory_manager=None,
                 platform_prompt="", agent_prompt=""):
        super().__init__()
        self.bridge = AgentBridge(
            graph=graph, config=config,
            memory_store=memory_store, memory_manager=memory_manager,
            platform_prompt=platform_prompt, agent_prompt=agent_prompt,
        )
        self._streaming_task: asyncio.Task | None = None
        self._is_streaming = False
        self._pending_text = ""

    # ── 布局 ───────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="chat-area"):
            yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
            yield Static("", id="streaming-text", classes="hidden")
        with Container(id="input-area"):
            with Horizontal():
                yield Label(">", id="prompt")
                yield Input(placeholder="输入消息 (Enter 发送, Ctrl+Q 退出)", id="user-input")
        yield Footer()

    def on_mount(self):
        """启动时初始化"""
        thread_id = self.bridge.config["configurable"]["thread_id"]
        self.sub_title = f"Session: {thread_id} | Ctrl+Q 退出"
        self.query_one("#user-input", Input).focus()
        asyncio.create_task(self._initialize_agent())

    async def _initialize_agent(self):
        """后台初始化 Agent"""
        await self.bridge.initialize()
        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"[{DIM_COLOR}][{_now()}] LangCode Agent 已就绪[/]")
        chat.write(f"[{DIM_COLOR}]输入消息开始对话，Ctrl+N 新会话，Ctrl+M 查看记忆[/]")

    # ── 输入处理 ───────────────────────────────────────

    @on(Input.Submitted, "#user-input")
    async def on_input(self, event: Input.Submitted):
        text = event.value.strip()
        if not text or self._is_streaming:
            return

        event.input.clear()
        self._is_streaming = True
        self._pending_text = ""

        # 写入用户消息
        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"\n[bold {USER_COLOR}]你[/] [{DIM_COLOR}]{_now()}[/]")
        chat.write(f"[{USER_COLOR}]{text}[/]\n")

        # 显示"思考中"指示
        streaming = self.query_one("#streaming-text", Static)
        streaming.remove_class("hidden")
        streaming.update(f"[{DIM_COLOR}]思考中...[/]")

        self.query_one("#prompt").update("⏳")

        self._streaming_task = asyncio.create_task(self._process_stream(text))

    async def _process_stream(self, text: str):
        """消费 AgentBridge 的事件流并更新 UI"""
        chat = self.query_one("#chat-log", RichLog)
        streaming = self.query_one("#streaming-text", Static)
        header_printed = False

        try:
            async for event in self.bridge.send_message(text):
                if event.type == "text_chunk":
                    if not header_printed:
                        chat.write(
                            f"[bold {AGENT_COLOR}]Agent[/] [{DIM_COLOR}]{_now()}[/]"
                        )
                        header_printed = True
                    self._pending_text += event.data
                    # 实时更新流式文本
                    streaming.update(self._pending_text)

                elif event.type == "tool_call":
                    # 先把已积累的文本写入日志
                    if self._pending_text:
                        chat.write(self._pending_text)
                        self._pending_text = ""
                        streaming.update("")
                    name = event.data["name"]
                    args = event.data.get("args", {})
                    args_str = str(args)[:200]
                    chat.write(
                        f"\n[bold {TOOL_COLOR}]  🔧 {name}[/]"
                        f"[{DIM_COLOR}]({args_str})[/]"
                    )
                    header_printed = False

                elif event.type == "tool_result":
                    name = event.data["name"]
                    content = str(event.data.get("content", ""))[:500]
                    chat.write(f"[{DIM_COLOR}]     → {content}[/]")

                elif event.type == "interrupt":
                    # 先写入已积累文本
                    if self._pending_text:
                        chat.write(self._pending_text)
                        self._pending_text = ""
                        streaming.update("")
                    question = event.data
                    result = await self.push_screen_wait(
                        InterruptModal(question)
                    )
                    if result == "ok":
                        self.bridge.set_interrupt_response("ok")
                    elif result == "skip":
                        self.bridge.set_interrupt_response("skip")
                        chat.write(f"[{DIM_COLOR}]已跳过确认[/]")
                    else:
                        self.bridge.set_interrupt_response("cancel")
                        chat.write(f"[{ERROR_COLOR}]已取消操作[/]")
                    header_printed = False

                elif event.type == "error":
                    if self._pending_text:
                        chat.write(self._pending_text)
                        self._pending_text = ""
                        streaming.update("")
                    chat.write(f"\n[{ERROR_COLOR}]错误: {event.data}[/]")

                elif event.type == "done":
                    # 将最后的流式文本写入日志
                    if self._pending_text:
                        chat.write(self._pending_text)
                        self._pending_text = ""
                    streaming.update("")
                    streaming.add_class("hidden")

        except asyncio.CancelledError:
            if self._pending_text:
                chat.write(f"{self._pending_text} [{DIM_COLOR}...[/]")
                self._pending_text = ""
            streaming.update("")
            streaming.add_class("hidden")
            chat.write(f"[{DIM_COLOR}]已取消[/]")

        except Exception as e:
            log.exception("流处理异常")
            if self._pending_text:
                chat.write(self._pending_text)
                self._pending_text = ""
            streaming.update("")
            streaming.add_class("hidden")
            chat.write(f"\n[{ERROR_COLOR}]处理异常: {e}[/]")

        finally:
            self._is_streaming = False
            self._streaming_task = None
            self.query_one("#prompt").update(">")
            self.query_one("#user-input", Input).focus()

    # ── 快捷键 ─────────────────────────────────────────

    async def action_new_session(self):
        """创建新会话"""
        if self._is_streaming:
            return
        chat = self.query_one("#chat-log", RichLog)
        chat.clear()
        chat.write(f"[{DIM_COLOR}][{_now()}] 开始新会话[/]")

    async def action_show_memory(self):
        """显示长期记忆"""
        if self._is_streaming or not self.bridge.memory_store:
            return
        chat = self.query_one("#chat-log", RichLog)
        records = self.bridge.memory_store.list_all()
        if not records:
            chat.write(f"\n[{DIM_COLOR}]暂无长期记忆[/]")
            return
        chat.write(f"\n[bold]📝 长期记忆 ({len(records)} 条)[/]")
        for r in records:
            tags = f" [{', '.join(r.tags)}]" if r.tags else ""
            chat.write(f"  [{DIM_COLOR}]{r.memory_type}[/]{tags} {r.content[:100]}")

    async def action_clear_screen(self):
        """清屏"""
        if self._is_streaming:
            return
        self.query_one("#chat-log", RichLog).clear()

    async def action_cancel_stream(self):
        """取消当前流式输出"""
        if self._streaming_task and not self._streaming_task.done():
            self._streaming_task.cancel()

    # ── 退出时自动保存记忆 ─────────────────────────────

    async def action_quit(self):
        """退出前自动保存记忆"""
        if self.bridge.memory_manager:
            try:
                current_state = self.bridge.graph.get_state(self.bridge.config)
                messages = current_state.values.get("messages", [])
                if messages:
                    saved = self.bridge.memory_manager.auto_save(messages)
                    if saved:
                        chat = self.query_one("#chat-log", RichLog)
                        chat.write(
                            f"\n[{DIM_COLOR}]已自动保存 {len(saved)} 条记忆[/]"
                        )
            except Exception:
                pass
        self.exit()


# ── 入口函数 ──────────────────────────────────────────────

def run_tui(graph, config, memory_store=None, memory_manager=None,
            platform_prompt="", agent_prompt=""):
    """启动 TUI"""
    app = LangCodeTUI(
        graph=graph, config=config,
        memory_store=memory_store, memory_manager=memory_manager,
        platform_prompt=platform_prompt, agent_prompt=agent_prompt,
    )
    app.run()
