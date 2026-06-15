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
import os
import asyncio
from typing import TYPE_CHECKING

# Windows 控制台默认 GBK 无法显示 emoji，强制 UTF-8
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    print("  输入消息开始对话，/help 查看可用命令，/skills 查看可用技能，/exit 退出\n")

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
            # 尝试作为 Skill 调用
            if engine.cfg.skill_runner:
                skill = _find_skill(engine, user_input)
                if skill:
                    _consume_and_print(_run_skill(engine, skill, user_input))
                    continue
                print(f"未知命令或技能: {user_input.split()[0]}，输入 /help 查看可用命令，/skills 查看可用技能")
                continue

        try:
            _consume_and_print(engine.submit_message(user_input))
        except RuntimeError as e:
            if "cannot schedule new futures after shutdown" in str(e):
                break
            raise


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


def _find_skill(engine: QueryEngine, user_input: str):
    """查找匹配的 Skill，找不到返回 None。"""
    from LangCode.agents.skills.loader import SkillLoader
    skill_name = user_input.strip().split()[0].lstrip("/")
    loader = SkillLoader(engine.cfg.workspace_dir)
    return next((s for s in loader.load_all() if s.name == skill_name), None)


def _run_skill(engine: QueryEngine, skill, user_input: str):
    """执行 Skill，返回 EngineEvent 生成器。"""
    from LangCode.engine.query_engine import EngineEvent

    args = user_input.strip().split(maxsplit=1)
    args = args[1] if len(args) > 1 else ""

    print(f"[执行技能] {skill.name}: {skill.description}")
    try:
        result = asyncio.run(engine.cfg.skill_runner.run_skill(skill, args))
    except Exception as e:
        log.error("Skill 执行失败: %s", e)
        result = f"[Skill 执行失败] {e}"

    yield EngineEvent(type="text_chunk", data=result)
    yield EngineEvent(type="done")
