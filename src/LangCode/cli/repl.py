"""cli/repl — 命令行交互循环。

参考 Claude Code REPL 设计：
- 流式输出 LLM 文本片段
- 工具调用和结果实时展示
- 斜杠命令处理（/mode, /session, /memory, /plan）
- 中断恢复（interrupt 时等待用户输入）
- Escape 取消流式输出（Ctrl+C）

与 v1 的关键差异：
  v1: run_conversation 手动 graph.stream() + _consume_events()
  v2: QueryEngine.submit_message() 封装完整生命周期
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from LangCode.shared.logger import get_logger

if TYPE_CHECKING:
    from LangCode.engine.query_engine import QueryEngine, EngineEvent

log = get_logger("cli.repl")

COMMAND_EXIT = "/exit"


def run_repl(engine: QueryEngine) -> None:
    """运行命令行交互循环。

    Args:
        engine: 已初始化的 QueryEngine 实例
    """
    print("\n[LangCode] Agent ready (v2)")
    print("  输入消息开始对话，/mode 查看权限模式，/exit 退出\n")

    while True:
        try:
            user_input = input("\n>: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n对话结束。")
            break

        if not user_input:
            continue

        if user_input.lower() == COMMAND_EXIT:
            _sync_title(engine)
            print("对话结束。")
            break

        if user_input.startswith("/"):
            from LangCode.cli.commands import handle_command
            handled = handle_command(engine, user_input)
            if handled:
                continue

        _consume_and_print(engine.submit_message(user_input))


def _consume_and_print(events) -> None:
    """消费引擎事件并打印到终端"""
    try:
        for event in events:
            if event.type == "text_chunk":
                print(event.data, end="", flush=True)

            elif event.type == "tool_call":
                args_preview = str(event.data.get("args", ""))[:300]
                print(f"\n[工具调用] {event.data['name']}({args_preview})", flush=True)

            elif event.type == "tool_result":
                name = event.data["name"]
                content = event.data.get("content", "")
                preview = content[:500] if isinstance(content, str) else str(content)[:500]
                print(f"\n[工具结果] {name}: {preview}", flush=True)

            elif event.type == "route":
                print(f"\n[路由] → {event.data}", flush=True)

            elif event.type == "plan":
                print(f"\n[计划] {event.data.get('node', '')}", flush=True)

            elif event.type == "verify":
                status = event.data.get("status", "")
                if status == "fail":
                    errors = event.data.get("errors", [])
                    print(f"\n[验证失败] {len(errors)} 个错误", flush=True)
                else:
                    print(f"\n[验证通过]", flush=True)

            elif event.type == "interrupt":
                question = event.data
                print(f"\nAgent 需要确认: {question}")
                try:
                    user_input = input(">: ").strip()
                except (KeyboardInterrupt, EOFError):
                    user_input = "cancel"
                # 恢复中断
                _consume_and_print(engine.resume_after_interrupt(user_input))
                return

            elif event.type == "error":
                print(f"\n[错误] {event.data}", flush=True)

            elif event.type == "done":
                print()  # 最后换行
                break

    except KeyboardInterrupt:
        print("\n[已取消]")


def _sync_title(engine: QueryEngine) -> None:
    """同步会话标题"""
    if engine.cfg.session_store and engine.cfg.current_session:
        state = engine.get_current_state()
        messages = state.get("messages", [])
        for m in messages:
            if m.type == "human" and m.content:
                engine.cfg.current_session.title = str(m.content)[:60]
                break
        engine.cfg.session_store.save(engine.cfg.current_session)
