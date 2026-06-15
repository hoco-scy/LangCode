"""cli.commands — 斜杠命令处理。

从 repl.py 提取的命令处理逻辑，支持独立扩展。

参考 Claude Code 斜杠命令系统：
- /help: 显示可用命令
- /mode: 权限模式管理
- /session: 会话信息
- /plan: 计划管理
- /memory: 记忆管理
- /skills: 技能列表
- /exit: 退出
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from LangCode.shared.logger import get_logger

if TYPE_CHECKING:
    from LangCode.engine.query_engine import QueryEngine

log = get_logger("cli.commands")


def handle_command(engine: "QueryEngine", user_input: str) -> bool:
    """处理斜杠命令，返回 True 表示已处理。

    Args:
        engine: QueryEngine 实例
        user_input: 用户输入（以 / 开头）

    Returns:
        True 表示命令已处理，False 表示未知命令
    """
    cmd = user_input.strip()

    # ── /help ──
    if cmd == "/help":
        return _cmd_help(engine)

    # ── /mode ──
    if cmd == "/mode" or cmd == "/mode status":
        return _cmd_mode_status(engine)
    if cmd.startswith("/mode "):
        mode = cmd.split(maxsplit=1)[1].strip()
        return _cmd_mode_set(engine, mode)

    # ── /session ──
    if cmd == "/session":
        return _cmd_session(engine)

    # ── /plan ──
    if cmd == "/plan":
        return _cmd_plan(engine)

    # ── /memory ──
    if cmd == "/memory":
        return _cmd_memory(engine)

    # ── /skills ──
    if cmd == "/skills":
        return _cmd_skills(engine)

    # ── /analytics ──
    if cmd == "/analytics":
        return _cmd_analytics(engine)

    return False


def _cmd_mode_status(engine: "QueryEngine") -> bool:
    """显示当前权限模式。"""
    from LangCode.state.app_state import get_app_state
    mode = get_app_state().session.agent_mode
    print(f"当前权限模式: {mode}")
    mode_desc = {
        "plan": "只读模式 — 仅允许读取和搜索操作",
        "accept_edits": "接受编辑 — 文件编辑自动通过，shell 需确认",
        "default": "默认 — 只读自动通过，写操作需确认",
        "dont_ask": "不询问 — 需确认的操作自动拒绝",
        "bypass": "绕过 — 全部自动批准",
    }
    if mode in mode_desc:
        print(f"  {mode_desc[mode]}")
    return True


def _cmd_mode_set(engine: "QueryEngine", mode: str) -> bool:
    """切换权限模式。"""
    from LangCode.state.app_state import update_app_state
    from dataclasses import replace

    valid_modes = ("plan", "accept_edits", "default", "dont_ask", "bypass")
    if mode not in valid_modes:
        print(f"无效模式: {mode}")
        print(f"可用模式: {', '.join(valid_modes)}")
        return True
    update_app_state(lambda prev: replace(prev, session=replace(prev.session, agent_mode=mode)))
    print(f"已切换到 {mode} 模式。")
    return True


def _cmd_session(engine: "QueryEngine") -> bool:
    """显示会话信息。"""
    from LangCode.state.app_state import get_app_state
    state = engine.get_current_state()
    msg_count = len(state.get("messages", []))
    plan = state.get("current_plan")
    mode = get_app_state().session.agent_mode
    plan_info = ", 计划进行中" if plan else ""
    print(f"当前会话: {msg_count} 条消息{plan_info}, 模式: {mode}")
    return True


def _cmd_plan(engine: "QueryEngine") -> bool:
    """显示当前计划。"""
    from LangCode.planning.schema import Plan

    state = engine.get_current_state()
    plan_data = state.get("current_plan")
    if not plan_data:
        print("当前没有活跃的执行计划。")
    else:
        try:
            plan = Plan(**plan_data)
            print(plan.to_display())
        except Exception as e:
            print(f"计划数据解析失败: {e}")
    return True


def _cmd_memory(engine: "QueryEngine") -> bool:
    """显示记忆列表。"""
    if not engine.cfg.memory_store:
        print("记忆系统未初始化。")
        return True

    records = engine.cfg.memory_store.list_all()
    if not records:
        print("暂无长期记忆。")
    else:
        print(f"共 {engine.cfg.memory_store.count()} 条记忆：")
        for r in records:
            tags = f" [{', '.join(r.tags)}]" if r.tags else ""
            print(f"  [{r.memory_type}]{tags} {r.content[:80]}")
    return True


def _cmd_skills(engine: "QueryEngine") -> bool:
    """显示可用技能。"""
    from LangCode.agents.skills.loader import SkillLoader

    loader = SkillLoader(engine.cfg.workspace_dir)
    skills = loader.load_all()

    builtin = [s for s in skills if "resources" in s.source_file.replace("\\", "/")]
    custom = [s for s in skills if s not in builtin]

    if builtin:
        print(f"内置技能 ({len(builtin)}):")
        for s in builtin:
            print(f"  /{s.name:<16s} {s.description}")
    if custom:
        print(f"自定义技能 ({len(custom)}):")
        for s in custom:
            print(f"  /{s.name:<16s} {s.description}")
    if not skills:
        print("暂无可用技能。")
    return True


def _cmd_analytics(engine: "QueryEngine") -> bool:
    """显示遥测数据。"""
    try:
        from LangCode.services.analytics import get_analytics
        snapshot = get_analytics().get_snapshot()
        print("遥测数据:")
        for k, v in snapshot.items():
            print(f"  {k}: {v}")
    except Exception:
        print("遥测数据不可用。")
    return True


_HELP_ENTRIES = [
    ("/help",      "显示本帮助信息"),
    ("/mode",      "查看当前权限模式"),
    ("/mode <m>",  "切换权限模式 (plan/accept_edits/default/dont_ask/bypass)"),
    ("/session",   "显示当前会话信息"),
    ("/plan",      "显示当前执行计划"),
    ("/memory",    "显示长期记忆列表"),
    ("/skills",    "列出可用技能"),
    ("/analytics", "显示遥测数据"),
    ("/exit",      "退出"),
    ("",           ""),
    ("/<skill>",   "执行自定义技能（如 /code-review）"),
]


def _cmd_help(engine: "QueryEngine") -> bool:
    """显示所有可用斜杠命令。"""
    print("可用命令：")
    for name, desc in _HELP_ENTRIES:
        if name:
            print(f"  {name:<16s} {desc}")
        elif desc:
            print(f"  {desc}")
    return True
