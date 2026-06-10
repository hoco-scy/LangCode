"""多 Agent 委托工具：工厂模式创建，避免全局变量注入"""

from langchain.tools import tool
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from LangCode.shared.logger import get_logger

log = get_logger("agents.delegate")


class DelegateInput(BaseModel):
    task: str = Field(description="要委派给子 Agent 的具体任务描述")
    context: str = Field(default="", description="额外的上下文信息")


def _make_delegate_tool(agent_name: str, agent_desc: str, agents: dict, get_session_id):
    """动态创建委托工具，通过参数注入 agents 而非全局变量。

    Args:
        get_session_id: 无参 callable，返回当前会话 ID，用于构造 session-scoped 子 Agent thread_id。
    """

    tool_name = f"delegate_to_{agent_name}"
    tool_description = f"将任务委派给{agent_desc}执行。适用于需要{agent_desc}的场景。"

    @tool(tool_name, args_schema=DelegateInput, return_direct=True, description=tool_description)
    def delegate(task: str, context: str = "") -> dict:
        """将任务委派给指定的专业 Agent 执行。用于需要专业能力的复杂任务。"""
        if agent_name not in agents:
            return {"success": False, "error": f"Agent '{agent_name}' 未注册"}

        agent = agents[agent_name]
        log.info("委派任务给 %s: %s", agent_name, task[:100])

        try:
            sub_graph = agent.get_graph()
            # session-scoped thread_id：同一会话内子 Agent 保持记忆，不同会话隔离
            sid = get_session_id()
            sub_config = {"configurable": {"thread_id": f"sub_{sid}_{agent_name}"}}

            # 注入系统提示
            system_prompt = agent.get_system_prompt()
            if context:
                system_prompt += f"\n\n## 额外上下文\n{context}"

            sub_graph.update_state(sub_config, {
                "messages": [SystemMessage(content=system_prompt)]
            })

            # 执行子 Agent，收集所有输出
            result_parts = []
            tool_calls_made = 0
            files_modified = []

            events = sub_graph.stream(
                {"messages": [HumanMessage(content=task)]},
                sub_config,
                stream_mode=["updates"],
            )

            for mode, data in events:
                if mode == "updates":
                    # 收集 agent 节点的文本输出
                    for node_name in ("agent", "synthesize_llm", "report"):
                        if node_name in data:
                            node_msg = data[node_name].get("messages")
                            if node_msg:
                                msgs = node_msg if isinstance(node_msg, list) else [node_msg]
                                for msg in msgs:
                                    if hasattr(msg, 'content') and msg.content:
                                        result_parts.append(msg.content)

                    # 统计工具调用
                    if "agent" in data:
                        agent_msg = data["agent"].get("messages")
                        if agent_msg:
                            msgs = agent_msg if isinstance(agent_msg, list) else [agent_msg]
                            for msg in msgs:
                                for tc in getattr(msg, "tool_calls", []) or []:
                                    tool_calls_made += 1
                                    args = tc.get("args", {})
                                    if tc.get("name") in ("write_file", "edit_file") and "file_path" in args:
                                        files_modified.append(args["file_path"])

            summary = "\n".join(result_parts) if result_parts else "子 Agent 未产生输出"
            log.info("子 Agent %s 完成: 工具调用=%d, 输出=%d 字符", agent_name, tool_calls_made, len(summary))
            return {
                "success": True,
                "agent": agent_name,
                "summary": summary[:3000],  # 截断过长输出，保留 3000 字符
                "tool_calls": tool_calls_made,
                "files_modified": list(set(files_modified)),
            }

        except Exception as e:
            log.error("子 Agent %s 执行失败: %s", agent_name, e)
            return {"success": False, "error": str(e), "agent": agent_name}

    return delegate


def create_delegate_tools(agents: dict, get_session_id) -> list:
    """创建所有委托工具

    Args:
        agents: {"code": CodeAgent, "research": ResearchAgent, "review": ReviewAgent}
        get_session_id: 无参 callable，返回当前会话 ID
    """
    return [
        _make_delegate_tool("code", "代码工程师：编写、修改、调试代码", agents, get_session_id),
        _make_delegate_tool("research", "代码研究员：搜索、阅读、分析代码库", agents, get_session_id),
        _make_delegate_tool("review", "代码审查员：审查代码质量、安全性", agents, get_session_id),
    ]
