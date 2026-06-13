"""LangCode AI Code Agent 入口

基于 LangGraph 的多 Agent 协作系统，具备记忆、规划、上下文管理等能力。

中枢路由架构：
- Supervisor 使用 structured output 决定路由（react/plan/code/research/review）
- plan 模式（只读）和 build 模式（全权限）权限管理
- 子路径完成后回环到 supervisor

用法:
    python main.py           # 命令行对话模式（默认）
    python main.py --tui     # TUI 终端界面模式
"""

import os
import sqlite3
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage, AIMessageChunk
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from LangCode.agents.supervisor import SupervisorAgent
from LangCode.shared import llm, all_tools, ast_tools, MCPManager, SessionStore, get_logger
from LangCode.shared.session import SessionRecord
from LangCode.shared.command import COMMAND_EXIT, COMMAND_MEMORY, COMMAND_PLAN
from LangCode.shared.prompts import get_platform_prompt

# 记忆系统
from LangCode.memory.store import SQLiteMemoryStore
from LangCode.memory.manager import MemoryManager
from LangCode.memory.tools import create_memory_tools

# 多Agent系统
from LangCode.agents.code_agent import CodeAgent
from LangCode.agents.research_agent import ResearchAgent
from LangCode.agents.review_agent import ReviewAgent

log = get_logger("main")

# checkpoint 持久化路径
_CHECKPOINT_DB = str(Path.home() / ".langcode" / "checkpoints.db")
# 当前会话 ID 容器
_session_box = {"id": None}


def _ensure_checkpoint_schema(conn):
    """检测并修复 checkpoint 表 schema（兼容旧版 langgraph-checkpoint-sqlite）"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)").fetchall()}
    if "type" in cols:
        return  # schema 已是新版，无需处理
    log.warning("检测到旧版 checkpoint schema，重建表")
    conn.executescript("""
        DROP TABLE IF EXISTS checkpoints;
        DROP TABLE IF EXISTS writes;
        DROP TABLE IF EXISTS blobs;
    """)
    conn.commit()
    SqliteSaver(conn).setup()


def create_agent():
    """创建完整的 Agent 及其所有子系统。

    返回 (graph, config, agent_prompt, platform_prompt,
           memory_store, memory_manager, mcp_manager,
           session_store, current_session)
    """
    # 记忆系统
    memory_store = SQLiteMemoryStore()
    memory_manager = MemoryManager(store=memory_store, llm=llm)
    memory_save, memory_search, memory_list = create_memory_tools(memory_store, memory_manager)

    # checkpoint 持久化（所有 Agent 共享同一个 SqliteSaver）
    ckpt_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    checkpointer.setup()
    _ensure_checkpoint_schema(ckpt_conn)

    # 子 Agent（不再需要 delegate_tools，由 supervisor 路由决定）
    research_tools = [t for t in all_tools if t.name in (
        "read_file", "search_files", "fetch_api"
    )] + [memory_search]
    review_tools = [t for t in all_tools if t.name in (
        "read_file", "search_files", "run_python", "execute_shell"
    )]
    sub_agents = {
        "code": CodeAgent(llm=llm, checkpoint=checkpointer, tools=all_tools),
        "research": ResearchAgent(llm=llm, checkpoint=checkpointer, tools=research_tools),
        "review": ReviewAgent(llm=llm, checkpoint=checkpointer, tools=review_tools),
    }

    # MCP 工具（可选，从 ~/.langcode/mcp.json 加载）
    mcp_manager = MCPManager()
    mcp_status = mcp_manager.connect_all()
    if mcp_status["connected"] > 0:
        log.info("MCP: %d/%d 服务器已连接", mcp_status["connected"], mcp_status["total"])
    mcp_tools = mcp_manager.create_langchain_tools()

    # Supervisor 的全量工具（不再包含 plan_create 和 delegate_tools）
    all_tools_full = (
        all_tools + ast_tools + mcp_tools +
        [memory_save, memory_search, memory_list]
    )

    # Supervisor Agent
    lc_agent = SupervisorAgent(llm=llm, sys_checkpoint=checkpointer, sys_tools=all_tools_full,
                               sub_agents=sub_agents)
    lc_graph = lc_agent.get_graph()
    lc_agent_prompt = lc_agent.get_agent_prompt()

    # 会话管理
    session_store = SessionStore()
    workspace = os.getcwd()
    session_id = __import__("uuid").uuid4().hex[:12]
    _session_box["id"] = session_id
    current_session = SessionRecord(id=session_id, workspace=workspace)

    config = {"configurable": {"thread_id": session_id}}
    platform_prompt = get_platform_prompt()

    return (lc_graph, config, lc_agent_prompt, platform_prompt,
            memory_store, memory_manager, mcp_manager,
            session_store, current_session)


def deal_command(graph, config: dict, user_input: str,
                 memory_store, session_store, current_session,
                 workspace: str):
    """处理命令，返回 (handled, current_session, config)"""
    import uuid as _uuid

    # /memory 命令
    if user_input == COMMAND_MEMORY:
        records = memory_store.list_all()
        if not records:
            print("暂无长期记忆。")
        else:
            print(f"共 {memory_store.count()} 条记忆：")
            for r in records:
                tags = f" [{', '.join(r.tags)}]" if r.tags else ""
                print(f"  [{r.memory_type}]{tags} {r.content[:80]}")
        return True, current_session, config

    # /plan 命令
    if user_input == COMMAND_PLAN:
        from LangCode.planning.schema import Plan
        state = graph.get_state(config)
        plan_data = state.values.get("current_plan")
        if not plan_data:
            print("当前没有活跃的执行计划。")
        else:
            try:
                plan = Plan(**plan_data)
                print(plan.to_display())
            except Exception as e:
                print(f"计划数据解析失败: {e}")
        return True, current_session, config

    # /mode 命令
    if user_input == "/mode" or user_input == "/mode status":
        state = graph.get_state(config)
        mode = state.values.get("agent_mode", "build")
        print(f"当前权限模式: {mode}")
        if mode == "plan":
            print("  可用工具: read_file, search_files, fetch_api, memory_search, memory_list")
        else:
            print("  可用工具: 全部（含写操作）")
        return True, current_session, config

    if user_input == "/mode plan":
        graph.update_state(config, {"agent_mode": "plan"})
        print("已切换到 plan（只读）模式。可用工具: read_file, search_files, fetch_api, memory_search, memory_list")
        return True, current_session, config

    if user_input == "/mode build":
        graph.update_state(config, {"agent_mode": "build"})
        print("已切换到 build（全权限）模式。")
        return True, current_session, config

    # /session 命令
    if user_input == "/session":
        state = graph.get_state(config)
        msg_count = len(state.values.get("messages", []))
        plan = state.values.get("current_plan")
        mode = state.values.get("agent_mode", "build")
        plan_info = f", 计划进行中 (步骤 {state.values.get('plan_step_index', 0) + 1})" if plan else ""
        print(f"当前会话: {current_session.id}  ({msg_count} 条消息{plan_info}, 模式: {mode})")
        return True, current_session, config

    if user_input == "/session list":
        sessions = session_store.list_sessions(workspace)
        if not sessions:
            print("该工作区暂无历史会话。")
        else:
            print(f"工作区 {workspace} 的历史会话：")
            for s in sessions:
                marker = " ←" if s.id == current_session.id else ""
                print(f"  {s.id}  {s.title[:40]}  ({s.updated_at[:19]}){marker}")
        return True, current_session, config

    if user_input == "/session new":
        _sync_title(graph, config, session_store, current_session)
        session_id = _uuid.uuid4().hex[:12]
        _session_box["id"] = session_id
        current_session = SessionRecord(id=session_id, workspace=workspace)
        config = {"configurable": {"thread_id": session_id}}
        print(f"已创建新会话: {session_id}")
        return True, current_session, config

    if user_input.startswith("/session "):
        target_id = user_input[len("/session "):].strip()
        record = session_store.get(target_id, workspace)
        if not record:
            print(f"未找到会话: {target_id}")
            return True, current_session, config
        _sync_title(graph, config, session_store, current_session)
        current_session = record
        _session_box["id"] = record.id
        config = {"configurable": {"thread_id": record.id}}
        state = graph.get_state(config)
        msg_count = len(state.values.get("messages", []))
        print(f"已切换到会话: {record.id}  {record.title[:40]}  ({msg_count} 条消息)")
        return True, current_session, config

    return False, current_session, config


def run_conversation(graph, config, platform_prompt=None, agent_prompt=None,
                     memory_store=None, memory_manager=None,
                     session_store=None, current_session=None):
    """运行交互式对话循环"""
    workspace = os.getcwd()
    log.info("run_conversation 启动, session=%s", current_session.id)

    current_state = graph.get_state(config)
    is_new_session = len(current_state.values.get("messages", [])) == 0

    # 全新会话注入平台 prompt
    if is_new_session:
        init_messages = []
        if platform_prompt:
            init_messages.append(SystemMessage(id="platform", content=platform_prompt))
        if agent_prompt:
            init_messages.append(SystemMessage(id="agent_role", content=agent_prompt))
        if init_messages:
            graph.update_state(config, {"messages": init_messages})
        session_store.save(current_session)

    while True:
        user_input = input("\n>: ").strip()
        if user_input.lower() == COMMAND_EXIT:
            log.info("用户退出对话")
            _sync_title(graph, config, session_store, current_session)
            print("对话结束。")
            break

        if user_input.startswith("/"):
            handled, current_session, config = deal_command(
                graph, config, user_input, memory_store,
                session_store, current_session, workspace,
            )
            if handled:
                continue

        # 检索相关记忆并注入
        memory_context = ""
        if memory_manager:
            memory_context = memory_manager.get_context(user_input)
            if memory_context:
                log.debug("注入记忆上下文: %d 字符", len(memory_context))
                graph.update_state(config, {"memory_context": memory_context})

        log.info("用户输入: %s", user_input[:200])
        events = graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config,
            stream_mode=["messages", "updates"],
        )
        _consume_events(graph, events, config)


def _sync_title(graph, config, session_store, current_session):
    """从 checkpoint 提取第一条用户消息作为会话标题，更新到 SessionStore"""
    messages = graph.get_state(config).values.get("messages", [])
    for m in messages:
        if m.type == "human" and m.content:
            current_session.title = str(m.content)[:60]
            break
    session_store.save(current_session)
    log.debug("会话元数据已同步: %s title=%s", current_session.id, current_session.title)


def _consume_events(graph, events, config):
    """处理事件流：流式打印 LLM 输出、工具调用与结果、中断恢复"""
    log.debug("开始消费事件流")

    _LLM_NODES = {"agent", "supervisor", "synthesize_llm", "report"}
    _TOOL_NODES = {"mode_tools", "tools"}

    while True:
        interrupted = False

        try:
            for mode, data in events:
                if mode == "messages":
                    chunk, _metadata = data
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        print(chunk.content, end="", flush=True)

                elif mode == "updates":
                    log.debug("收到 updates: %s", list(data.keys()))

                    for key in data:
                        if key in _LLM_NODES:
                            node_msgs = data[key].get("messages")
                            if node_msgs:
                                msgs = node_msgs if isinstance(node_msgs, list) else [node_msgs]
                                for msg in msgs:
                                    for tc in getattr(msg, "tool_calls", []) or []:
                                        args_preview = str(tc.get("args", ""))[:300]
                                        print(f"\n[工具调用] {tc['name']}({args_preview})", flush=True)
                                        log.info("工具调用: %s args=%s", tc["name"], args_preview)

                        elif key in _TOOL_NODES:
                            for msg in data[key].get("messages", []):
                                tool_name = getattr(msg, "name", "unknown")
                                content = getattr(msg, "content", "")
                                preview = content[:500] if isinstance(content, str) else str(content)[:500]
                                print(f"\n[工具结果] {tool_name}: {preview}", flush=True)
                                log.debug("工具结果: %s -> %s", tool_name, preview[:200])

                        elif key == "supervisor":
                            # supervisor 路由决策
                            route = data[key].get("route", "")
                            reasoning = data[key].get("reasoning", "")
                            mode_val = data[key].get("agent_mode", "build")
                            if route:
                                print(f"\n[路由] → {route} (模式: {mode_val})", flush=True)
                                log.info("supervisor 路由: %s (mode=%s)", route, mode_val)

                    if "__interrupt__" in data:
                        interrupt_info = data["__interrupt__"]
                        log.info("触发中断: %s", interrupt_info[0].value)
                        print(f"\nAgent 需要确认: {interrupt_info[0].value}")
                        user_input = input(">: ").strip()
                        log.info("中断恢复输入: %s", user_input)
                        events = graph.stream(
                            Command(resume=user_input), config,
                            stream_mode=["messages", "updates"],
                        )
                        interrupted = True
                        break
        except Exception as e:
            log.error("事件流异常: %s", e)
            print(f"\n[错误] {type(e).__name__}: {e}")
            break

        if not interrupted:
            log.debug("事件流结束")
            print()
            break


if __name__ == "__main__":
    import sys
    import atexit

    if "--tui" in sys.argv: # 暂时处于不可用状态
        from LangCode.tui import run_tui
        log.info("=== LangCode Agent 启动 (TUI 模式) ===")
        lc_graph, config, agent_prompt, platform_prompt, \
            memory_store, memory_manager, mcp_manager, \
            session_store, current_session = create_agent()
        atexit.register(mcp_manager.disconnect_all)
        run_tui(lc_graph, config,
                platform_prompt=platform_prompt,
                agent_prompt=agent_prompt,
                memory_store=memory_store,
                memory_manager=memory_manager)
    else:
        log.info("=== LangCode Agent 启动 ===")
        lc_graph, config, agent_prompt, platform_prompt, \
            memory_store, memory_manager, mcp_manager, \
            session_store, current_session = create_agent()
        atexit.register(mcp_manager.disconnect_all)
        run_conversation(lc_graph, config,
                         platform_prompt=platform_prompt,
                         agent_prompt=agent_prompt,
                         memory_store=memory_store,
                         memory_manager=memory_manager,
                         session_store=session_store,
                         current_session=current_session)
