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

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from LangCode.services.config import Config
from LangCode.services.llm import LLMClient
from LangCode.services.analytics import init_analytics
from LangCode.state.app_state import init_app_state, get_app_state
from LangCode.engine.query_engine import QueryEngine, QueryEngineConfig
from LangCode.agents.definition import EXPLORE_AGENT, REVIEW_AGENT
from LangCode.agents.graph_builder import (
    build_supervisor_graph, build_explore_subgraph, build_review_subgraph,
)
from LangCode.agents.prompts import get_platform_prompt
from LangCode.shared.logger import get_logger
from LangCode.tools.registry import (
    ToolRegistry, register_all_builtin_tools, register_ast_tools,
    register_memory_tools, register_plan_tools, register_mcp_tools,
)
from LangCode.tools.context import ToolUseContext
from LangCode.state.session import SessionStore, SessionRecord
from LangCode.memory.store import SQLiteMemoryStore
from LangCode.memory.manager import MemoryManager
from LangCode.permissions.rules import RuleEngine
from LangCode.permissions.sandbox import PathSandbox

log = get_logger("main")

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
    3. Analytics（遥测）
    4. LLMClient
    5. Permission 系统（RuleEngine + PathSandbox）
    6. 工具注册（ToolRegistry 统一管理）
    7. 记忆系统
    8. Checkpoint
    9. 子图（Explore, Review）
    10. Supervisor 主图
    11. SessionStore + SessionRecord
    12. ToolUseContext
    13. QueryEngine
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

    # ── 3. Analytics ──
    analytics = init_analytics()

    # ── 4. LLM ──
    llm_client = LLMClient(config)
    llm = llm_client.primary_model

    # ── 5. 权限系统 ──
    rule_engine = RuleEngine()
    rule_engine.load_rules(workspace)
    path_sandbox = PathSandbox(workspace)

    # ── 6. 工具注册（通过 ToolRegistry 统一管理） ──
    registry = ToolRegistry()
    register_all_builtin_tools(registry)
    register_ast_tools(registry)

    # ── 7. 记忆系统 ──
    memory_store = SQLiteMemoryStore()
    memory_manager = MemoryManager(store=memory_store, llm=llm)
    register_memory_tools(registry, memory_store, memory_manager)

    # ── 7b. 规划工具 ──
    register_plan_tools(registry)

    # ── 7c. MCP 工具 ──
    try:
        register_mcp_tools(registry)
    except Exception as e:
        log.debug("MCP 跳过: %s", e)

    log.info("工具注册完成: %d 个工具", registry.tool_count)

    # ── 8. Checkpoint ──
    ckpt_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    checkpointer.setup()
    _ensure_checkpoint_schema(ckpt_conn)

    # ── 9. 子图 ──
    all_lc_tools = registry.to_langchain_tools(mode="default")
    explore_graph = build_explore_subgraph(llm, all_lc_tools, checkpointer=checkpointer)
    review_graph = build_review_subgraph(llm, all_lc_tools, checkpointer=checkpointer)

    # ── 10. Supervisor 主图 ──
    supervisor_graph = build_supervisor_graph(
        llm=llm,
        tools=all_lc_tools,
        checkpointer=checkpointer,
        sub_agent_graphs={
            "explore": explore_graph,
            "review": review_graph,
        },
    )

    # ── 11. 会话管理 ──
    session_store = SessionStore()
    session_id = uuid.uuid4().hex[:12]
    current_session = SessionRecord(id=session_id, workspace=workspace)

    config_dict = {"configurable": {"thread_id": session_id}}
    platform_prompt = get_platform_prompt()

    # Agent 提示词
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

    # ── 12. ToolUseContext ──
    tool_context = ToolUseContext(
        session_id=session_id,
        agent_id="supervisor",
        workspace_dir=workspace,
        model_name=llm_client.model_name,
        permission_mode=config.get_permission_mode(),
        allowed_dirs={workspace},
    )

    # ── 13. QueryEngine ──
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
        tool_registry=registry,
        rule_engine=rule_engine,
        path_sandbox=path_sandbox,
        tool_context=tool_context,
        analytics=analytics,
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
