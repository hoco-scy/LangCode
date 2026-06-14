"""LangCode AI Code Agent 入口（v2 重构）

基于 LangGraph 的多 Agent 协作系统，具备记忆、规划、自动验证等能力。

v2 架构：
- QueryEngine 统一管理会话生命周期
- ToolRegistry 统一工具注册中心
- AppState Store 响应式状态管理
- 1 主 Agent + 2 子图（Explore, Review）
- auto_verify 代码修改自动验证
- plan_create/delegate_* tool calling 驱动路由

用法：
    python main.py           # 命令行对话模式（默认）
    python main.py --tui     # TUI 终端界面模式（待实现）
"""

import os
import sys
import sqlite3
import uuid
import platform
from pathlib import Path
from datetime import datetime, timezone

from langchain_core.messages import SystemMessage, HumanMessage, AIMessageChunk
from langgraph.checkpoint.sqlite import SqliteSaver

# v2 新模块
from LangCode.services.config import Config
from LangCode.services.llm import LLMClient
from LangCode.state.app_state import init_app_state, get_app_state
from LangCode.engine.query_engine import QueryEngine, QueryEngineConfig
from LangCode.agents.definition import EXPLORE_AGENT, REVIEW_AGENT
from LangCode.agents.graph_builder import (
    build_supervisor_graph, build_explore_subgraph, build_review_subgraph,
)
from LangCode.agents.prompts import get_platform_prompt
from LangCode.shared.logger import get_logger

# 工具系统
from LangCode.tools.builtin import all_tools
from LangCode.tools.ast import ast_tools
from LangCode.state.session import SessionStore, SessionRecord
from LangCode.memory.store import SQLiteMemoryStore
from LangCode.memory.manager import MemoryManager
from LangCode.memory.tools import create_memory_tools
from LangCode.planning.planner import create_plan_tool

log = get_logger("main")

# checkpoint 持久化路径
_CHECKPOINT_DB = str(Path.home() / ".langcode" / "checkpoints.db")


def _ensure_checkpoint_schema(conn):
    """检测并修复 checkpoint 表 schema"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)").fetchall()}
    if "type" in cols:
        return
    log.warning("检测到旧版 checkpoint schema，重建表")
    conn.executescript("""
        DROP TABLE IF EXISTS checkpoints;
        DROP TABLE IF EXISTS writes;
        DROP TABLE IF EXISTS blobs;
    """)
    conn.commit()
    SqliteSaver(conn).setup()


def create_engine(workspace_dir: str = None) -> QueryEngine:
    """组装所有子系统，创建 QueryEngine。

    组装顺序（严格按依赖关系）：
    1. Config（分层配置）
    2. AppState（全局 Store）
    3. LLMClient
    4. 工具注册（内置 + AST + MCP + 记忆 + 规划）
    5. 记忆系统
    6. Checkpoint
    7. 子图（Explore, Review）
    8. Supervisor 主图
    9. SessionStore + SessionRecord
    10. QueryEngine
    """
    workspace = workspace_dir or os.getcwd()

    # ── 1. 配置 ──
    config = Config.load(workspace)
    model_cfg = config.get_model()

    # ── 2. AppState ──
    os_name = platform.system().lower()
    if os_name == "darwin":
        os_name = "mac"
    init_app_state(
        platform=os_name,
        workspace_dir=workspace,
        agent_mode=config.get_permission_mode(),
    )

    # ── 3. LLM ──
    llm_client = LLMClient(config)
    llm = llm_client.primary_model

    # ── 4. 工具组装 ──
    tools = list(all_tools) + list(ast_tools)

    # ── 5. 记忆系统 ──
    memory_store = SQLiteMemoryStore()
    memory_manager = MemoryManager(store=memory_store, llm=llm)
    memory_save, memory_search, memory_list = create_memory_tools(memory_store, memory_manager)
    tools.extend([memory_save, memory_search, memory_list])

    # ── 5b. 规划工具 ──
    plan_tool = create_plan_tool()
    tools.append(plan_tool)

    # ── 5c. MCP 工具 ──
    try:
        from LangCode.tools.mcp import MCPManager
        mcp_manager = MCPManager()
        mcp_status = mcp_manager.connect_all()
        if mcp_status["connected"] > 0:
            log.info("MCP: %d/%d 服务器已连接", mcp_status["connected"], mcp_status["total"])
            tools.extend(mcp_manager.create_langchain_tools())
    except Exception as e:
        log.debug("MCP 跳过: %s", e)
        mcp_manager = None

    # ── 6. Checkpoint ──
    ckpt_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    checkpointer.setup()
    _ensure_checkpoint_schema(ckpt_conn)

    # ── 7. 子图 ──
    explore_graph = build_explore_subgraph(llm, tools, checkpointer=checkpointer)
    review_graph = build_review_subgraph(llm, tools, checkpointer=checkpointer)

    # ── 8. Supervisor 主图 ──
    supervisor_graph = build_supervisor_graph(
        llm=llm,
        tools=tools,
        checkpointer=checkpointer,
        sub_agent_graphs={
            "explore": explore_graph,
            "review": review_graph,
        },
    )

    # ── 9. 会话管理 ──
    session_store = SessionStore()
    session_id = uuid.uuid4().hex[:12]
    current_session = SessionRecord(id=session_id, workspace=workspace)

    config_dict = {"configurable": {"thread_id": session_id}}
    platform_prompt = get_platform_prompt()

    # Agent 提示词
    from LangCode.agents.definition import EXPLORE_AGENT
    agent_prompt = """你是一个编程智能体，也是多 Agent 系统的协调者。

## 核心行为

- **简单任务**（只需一步操作，如读文件、回答问题）→ 直接调用对应工具
- **复杂任务**（需要3步及以上操作）→ 调用 plan_create 工具创建执行计划
- **专项任务**（代码研究、代码审查）→ 调用对应的 delegate 工具委派给专业 Agent

## 工具使用优先级

1. 结构化代码修改 → ast_rename / ast_add_param
2. 精确替换 → edit_file
3. 新建/覆盖 → write_file

## 计划执行规则

当系统注入了计划执行上下文时：
- 严格按当前步骤操作，不要偏离
- 完成当前步骤后用简洁文字总结结果
- 不要重复已完成的步骤

## 行为准则

- 每次工具调用应有明确目的，避免无意义的重复调用
- 当用户表达偏好或做出重要决策时，使用 memory_save 记住
- 回答简洁准确，必要时附上代码示例
"""

    # ── 10. QueryEngine ──
    engine = QueryEngine(QueryEngineConfig(
        workspace_dir=workspace,
        graph=supervisor_graph,
        config=config_dict,
        agent_prompt=agent_prompt,
        platform_prompt=platform_prompt,
        memory_store=memory_store,
        memory_manager=memory_manager,
        session_store=session_store,
        current_session=current_session,
    ))

    return engine


def main():
    """入口"""
    engine = create_engine()

    if "--tui" in sys.argv:
        print("TUI 模式暂未实现，请使用默认命令行模式。")
        sys.exit(1)
    else:
        from LangCode.cli.repl import run_repl
        run_repl(engine)


if __name__ == "__main__":
    main()
