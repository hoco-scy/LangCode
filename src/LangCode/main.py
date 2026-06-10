"""LangCode AI Code Agent 入口

基于 LangGraph 的多 Agent 协作系统，具备记忆、规划、上下文管理等能力。

用法:
    python main.py           # 命令行对话模式（默认）
    python main.py --tui     # TUI 终端界面模式
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from LangCode.agents.supervisor import SupervisorAgent
from LangCode.shared import llm, all_tools, ast_tools, MCPManager, get_logger
from LangCode.shared.command import COMMAND_EXIT, COMMAND_MEMORY
from LangCode.shared.prompts import get_platform_prompt

# 记忆系统
from LangCode.memory.store import SQLiteMemoryStore
from LangCode.memory.manager import MemoryManager
from LangCode.memory.tools import create_memory_tools

# 规划系统
from LangCode.planning.tools import plan_create, plan_show

# 多Agent系统
from LangCode.agents.code_agent import CodeAgent
from LangCode.agents.research_agent import ResearchAgent
from LangCode.agents.review_agent import ReviewAgent
from LangCode.agents.delegate_tools import create_delegate_tools

log = get_logger("main")


def create_agent():
    """创建完整的 Agent 及其所有子系统。返回 (graph, config, agent_prompt, platform_prompt)"""
    # 记忆系统
    memory_store = SQLiteMemoryStore(db_path=".langcode/memory.db")
    memory_manager = MemoryManager(store=memory_store, llm=llm)
    memory_save, memory_search, memory_list = create_memory_tools(memory_store, memory_manager)

    # 子 Agent
    lc_checkpoint_sub = MemorySaver()
    research_tools = [t for t in all_tools if t.name in ("read_file", "search_files", "fetch_api")] + [memory_search]
    review_tools = [t for t in all_tools if t.name in ("read_file", "search_files", "run_python", "execute_shell")]
    sub_agents = {
        "code": CodeAgent(llm=llm, checkpoint=lc_checkpoint_sub, tools=all_tools),
        "research": ResearchAgent(llm=llm, checkpoint=lc_checkpoint_sub, tools=research_tools),
        "review": ReviewAgent(llm=llm, checkpoint=lc_checkpoint_sub, tools=review_tools),
    }

    delegate_tools = create_delegate_tools(sub_agents)

    # MCP 工具（可选，从 .langcode/mcp.json 加载）
    mcp_manager = MCPManager()
    mcp_status = mcp_manager.connect_all()
    if mcp_status["connected"] > 0:
        log.info("MCP: %d/%d 服务器已连接", mcp_status["connected"], mcp_status["total"])
    mcp_tools = mcp_manager.create_langchain_tools()

    # 合并所有工具
    all_tools_full = (
        all_tools + ast_tools + mcp_tools +
        [memory_save, memory_search, memory_list, plan_create, plan_show] +
        delegate_tools
    )

    # Supervisor Agent
    lc_checkpoint = MemorySaver()
    lc_agent = SupervisorAgent(llm=llm, sys_checkpoint=lc_checkpoint, sys_tools=all_tools_full)
    lc_graph = lc_agent.get_graph()
    lc_agent_prompt = lc_agent.get_agent_prompt()

    config = {"configurable": {"thread_id": "test_001"}}
    platform_prompt = get_platform_prompt()

    return lc_graph, config, lc_agent_prompt, platform_prompt, memory_store, memory_manager


def deal_command(graph, config: dict, user_input: str, memory_store) -> bool:
    """处理命令，返回 True 表示已处理"""
    if user_input == COMMAND_MEMORY:
        records = memory_store.list_all()
        if not records:
            print("暂无长期记忆。")
        else:
            print(f"共 {memory_store.count()} 条记忆：")
            for r in records:
                tags = f" [{', '.join(r.tags)}]" if r.tags else ""
                print(f"  [{r.memory_type}]{tags} {r.content[:80]}")
        return True
    return False


def run_conversation(graph, config, platform_prompt=None, agent_prompt=None,
                     memory_store=None, memory_manager=None):
    """运行交互式对话循环"""
    log.info("run_conversation 启动, config=%s", config)
    current_state = graph.get_state(config)
    is_new_session = len(current_state.values.get("messages", [])) == 0
    log.debug("新会话: %s, 消息数: %d", is_new_session, len(current_state.values.get("messages", [])))

    # 全新会话注入平台 prompt
    init_messages = []
    if is_new_session and platform_prompt:
        init_messages.append(SystemMessage(id="platform", content=platform_prompt))

    if agent_prompt:
        init_messages.append(SystemMessage(id="agent_role", content=agent_prompt))

    if init_messages:
        log.debug("注入 %d 条系统消息", len(init_messages))
        graph.update_state(config, {"messages": init_messages})

    while True:
        user_input = input("\n>: ").strip()
        if user_input.lower() == COMMAND_EXIT:
            log.info("用户退出对话")
            if memory_manager:
                current_state = graph.get_state(config)
                messages = current_state.values.get("messages", [])
                if messages:
                    saved = memory_manager.auto_save(messages)
                    if saved:
                        print(f"已自动保存 {len(saved)} 条记忆。")
            print("对话结束。")
            break

        if user_input.startswith("/"):
            if deal_command(graph, config, user_input, memory_store):
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


def _consume_events(graph, events, config):
    """处理事件流：流式打印 LLM 输出、工具调用与结果、中断恢复"""
    log.debug("开始消费事件流")

    while True:
        interrupted = False

        for mode, data in events:
            if mode == "messages":
                chunk, _metadata = data
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    print(chunk.content, end="", flush=True)

            elif mode == "updates":
                log.debug("收到 updates: %s", list(data.keys()))

                if "agent" in data:
                    agent_msg = data["agent"].get("messages")
                    if agent_msg:
                        msgs = agent_msg if isinstance(agent_msg, list) else [agent_msg]
                        for msg in msgs:
                            for tc in getattr(msg, "tool_calls", []) or []:
                                args_preview = str(tc.get("args", ""))[:300]
                                print(f"\n[工具调用] {tc['name']}({args_preview})", flush=True)
                                log.info("工具调用: %s args=%s", tc["name"], args_preview)

                if "tools" in data:
                    for msg in data["tools"].get("messages", []):
                        tool_name = getattr(msg, "name", "unknown")
                        content = getattr(msg, "content", "")
                        preview = content[:500] if isinstance(content, str) else str(content)[:500]
                        print(f"\n[工具结果] {tool_name}: {preview}", flush=True)
                        log.debug("工具结果: %s -> %s", tool_name, preview[:200])

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

        if not interrupted:
            log.debug("事件流结束")
            print()
            break


if __name__ == "__main__":
    import sys

    if "--tui" in sys.argv: # 暂时处于不可用状态
        from LangCode.tui import run_tui
        log.info("=== LangCode Agent 启动 (TUI 模式) ===")
        lc_graph, config, agent_prompt, platform_prompt, memory_store, memory_manager = create_agent()
        run_tui(lc_graph, config,
                platform_prompt=platform_prompt,
                agent_prompt=agent_prompt,
                memory_store=memory_store,
                memory_manager=memory_manager)
    else:
        log.info("=== LangCode Agent 启动 ===")
        lc_graph, config, agent_prompt, platform_prompt, memory_store, memory_manager = create_agent()
        run_conversation(lc_graph, config,
                         platform_prompt=platform_prompt,
                         agent_prompt=agent_prompt,
                         memory_store=memory_store,
                         memory_manager=memory_manager)
