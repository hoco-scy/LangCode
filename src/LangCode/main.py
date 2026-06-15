"""LangCode AI Code Agent 入口（v2 重构）

基于 LangGraph 的多 Agent 协作系统，具备记忆、规划、自动验证等能力。

v2 架构：
- QueryEngine 统一管理会话生命周期
- ToolRegistry 统一工具注册中心
- AppState Store 响应式状态管理
- 1 主 Agent + 2 子图（Explore, Review）
- auto_verify 代码修改自动验证
- write_todo/update_todo/modify_todo 工具化计划管理
- delegate_* tool calling 驱动子图路由

用法：
    python main.py           # 命令行对话模式（默认）
    python main.py --tui     # TUI 终端界面模式（待实现）
"""

import os
import sys
import shutil
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
from LangCode.state.transcript import TranscriptWriter, TranscriptReader
from LangCode.memory.store import SQLiteMemoryStore
from LangCode.memory.manager import MemoryManager
from LangCode.permissions.rules import RuleEngine
from LangCode.permissions.sandbox import PathSandbox

log = get_logger("main")

_LANGCODE_DIR = Path.home() / ".langcode"
_CHECKPOINT_DB = str(_LANGCODE_DIR / "checkpoints.db")

_AGENT_PROMPT = """你叫LangCode，是一个专为编程特化的智能体，也是多 Agent 系统的协调者。

## 核心行为

- **简单任务**（只需一步操作，如读文件、回答问题）→ 直接调用对应工具
- **复杂任务**（需要3步及以上操作）→ 调用 write_todo 工具创建执行计划
- **专项任务**（代码研究、代码审查）→ 调用对应的 delegate 工具委派给专业 Agent

## 工具使用优先级

1. 结构化代码修改 → ast_rename / ast_add_param
2. 精确替换 → edit_file
3. 新建/覆盖 → write_file

## 计划管理

- 创建计划后，系统会在每轮对话中注入当前计划和执行规则
- 严格按照计划执行，每完成一步及时调用 update_todo 标记完成
- 需要调整计划时调用 modify_todo

## 行为准则

- 每次工具调用应有明确目的，避免无意义的重复调用
- 当用户表达偏好或做出重要决策时，使用 memory_save 记住
- 回答简洁准确，必要时附上代码示例
"""


def _ensure_checkpoint_schema(conn):
    """检测并修复 checkpoint 表 schema，迁移前自动备份。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)").fetchall()}
    if "type" in cols:
        return
    # 备份旧数据库
    db_path = Path(_CHECKPOINT_DB)
    if db_path.exists():
        backup = db_path.with_suffix(".db.bak")
        shutil.copy2(db_path, backup)
        log.warning("旧版 checkpoint schema，已备份到 %s", backup)
    conn.executescript("""
        DROP TABLE IF EXISTS checkpoints;
        DROP TABLE IF EXISTS writes;
        DROP TABLE IF EXISTS blobs;
    """)
    conn.commit()
    SqliteSaver(conn).setup()


def create_engine(workspace_dir: str = None) -> QueryEngine:
    """组装所有子系统，创建 QueryEngine。"""
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

    # ── 6. 工具注册 ──
    registry = ToolRegistry()
    register_all_builtin_tools(registry)
    register_ast_tools(registry)

    # ── 7. 记忆系统 ──
    memory_store = SQLiteMemoryStore()
    memory_manager = MemoryManager(store=memory_store, llm=llm)
    register_memory_tools(registry, memory_store, memory_manager)
    register_plan_tools(registry)

    # ── 7b. MCP 工具 ──
    try:
        register_mcp_tools(registry)
    except Exception as e:
        log.warning("MCP 工具注册失败（已跳过）: %s", e)

    log.info("工具注册完成: %d 个工具", registry.tool_count)

    # ── 8. Checkpoint ──
    _LANGCODE_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    checkpointer.setup()
    _ensure_checkpoint_schema(ckpt_conn)

    # ── 9. 子图 ──
    all_lc_tools = registry.to_langchain_tools(mode="default")
    explore_graph = build_explore_subgraph(llm, all_lc_tools, checkpointer=checkpointer, llm_client=llm_client)
    review_graph = build_review_subgraph(llm, all_lc_tools, checkpointer=checkpointer, llm_client=llm_client)

    # ── 10. Supervisor 主图 ──
    supervisor_graph = build_supervisor_graph(
        llm=llm,
        tools=all_lc_tools,
        checkpointer=checkpointer,
        sub_agent_graphs={
            "explore": explore_graph,
            "review": review_graph,
        },
        llm_client=llm_client,
    )

    # ── 11. 会话管理 ──
    session_store = SessionStore()
    session_id = uuid.uuid4().hex[:12]
    current_session = SessionRecord(id=session_id, workspace=workspace)
    transcript = TranscriptWriter(session_id=session_id)

    config_dict = {"configurable": {"thread_id": session_id}}
    platform_prompt = get_platform_prompt()

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
        agent_prompt=_AGENT_PROMPT,
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
        transcript=transcript,
    ))
    engine._ckpt_conn = ckpt_conn

    return engine


def main():
    """入口"""
    engine = create_engine()

    if "--tui" in sys.argv:
        print("TUI 模式暂未实现，请使用默认命令行模式。")
        sys.exit(1)
    else:
        from LangCode.cli.repl import run_repl
        try:
            run_repl(engine)
        finally:
            engine.close()


if __name__ == "__main__":
    main()
