# Main entry point for the application

from langchain_core.messages import SystemMessage, HumanMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from LangCode.agents.supervisor.graph import SupervisorAgent
from LangCode.shared.llm import llm
from LangCode.shared.tools import all_tools
from LangCode.shared.command import *
from LangCode.shared.prompts import get_platform_prompt
from LangCode.shared.logger import get_logger

log = get_logger("main")


# 当前仅有一个智能体，后续可能会继续完善


def deal_command(graph, config: dict) -> dict:
    pass


def run_conversation(
    graph,
    config,
    platform_prompt: str = None,
    agent_prompt: str = None
):
    """
    platform_prompt: 平台级 prompt，整个会话只注入一次
    agent_prompt:    agent 级 prompt，切换 agent 时可以替换
    """
    log.info("run_conversation 启动, config=%s", config)
    current_state = graph.get_state(config)
    is_new_session = len(current_state.values.get("messages", [])) == 0
    log.debug("新会话: %s, 消息数: %d", is_new_session, len(current_state.values.get("messages", [])))

    # 只在全新会话注入平台 prompt
    init_messages = []
    if is_new_session and platform_prompt:
        init_messages.append(
            SystemMessage(id="platform", content=platform_prompt)
        )

    # agent prompt 每次都可以传入（替换上一个 agent 的 prompt）
    if agent_prompt:
        init_messages.append(
            SystemMessage(id="agent_role", content=agent_prompt)
        )

    if init_messages:
        log.debug("注入 %d 条系统消息", len(init_messages))
        # 只注入配置，不触发 agent 实际执行
        graph.update_state(config, {"messages": init_messages})

    # 主对话循环
    while True:
        user_input = input("\n>: ").strip()
        if user_input.lower() == COMMAND_EXIT:
            log.info("用户退出对话")
            print("对话结束。")
            break

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
                if isinstance(chunk, AIMessageChunk):
                    if chunk.content:
                        print(chunk.content, end="", flush=True)

            elif mode == "updates":
                log.debug("收到 updates: %s", list(data.keys()))

                # agent 节点完成：打印完整的工具调用请求（此时 args 已齐全）
                if "agent" in data:
                    agent_msg = data["agent"].get("messages")
                    if agent_msg:
                        # updates 里可能是 list 或单条
                        msgs = agent_msg if isinstance(agent_msg, list) else [agent_msg]
                        for msg in msgs:
                            for tc in getattr(msg, "tool_calls", []) or []:
                                args_preview = str(tc.get("args", ""))[:300]
                                print(f"\n[工具调用] {tc['name']}({args_preview})", flush=True)
                                log.info("工具调用: %s args=%s", tc["name"], args_preview)

                # tools 节点完成：打印结果摘要
                if "tools" in data:
                    for msg in data["tools"].get("messages", []):
                        tool_name = getattr(msg, "name", "unknown")
                        content = getattr(msg, "content", "")
                        preview = content[:500] if isinstance(content, str) else str(content)[:500]
                        print(f"\n[工具结果] {tool_name}: {preview}", flush=True)
                        log.debug("工具结果: %s -> %s", tool_name, preview[:200])

                # human-in-the-loop 中断
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


def create_new_session() -> dict:
    # 本质是创建一个新的config
    pass


if __name__ == "__main__":
    log.info("=== LangCode Agent 启动 ===")
    config = {
        "configurable": {
            "thread_id": "test_001"
        }}

    lc_checkpoint = MemorySaver()

    lc_agent = SupervisorAgent(llm=llm, sys_checkpoint=lc_checkpoint, sys_tools=all_tools)
    lc_graph = lc_agent.get_graph()
    lc_agent_prompt = lc_agent.get_agent_prompt()

    platform_prompt = get_platform_prompt()

    run_conversation(lc_graph, config, platform_prompt=platform_prompt, agent_prompt=lc_agent_prompt)
