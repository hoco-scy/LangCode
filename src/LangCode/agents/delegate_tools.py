"""多 Agent 委托工具：Supervisor 通过这些工具将任务委派给专业 Agent"""

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("agents.delegate")

# 全局引用，由 main.py 注入
_agents = {}


def init_delegate_tools(agents: dict):
    """注入子 Agent 实例"""
    global _agents
    _agents = agents


class DelegateInput(BaseModel):
    task: str = Field(description="要委派给子 Agent 的具体任务描述")
    context: str = Field(default="", description="额外的上下文信息")


def _make_delegate_tool(agent_name: str, agent_desc: str):
    """动态创建委托工具"""
    tool_name = f"delegate_to_{agent_name}"

    @tool(tool_name, args_schema=DelegateInput, return_direct=True)
    def delegate(task: str, context: str = "") -> dict:
        """将任务委派给指定的专业 Agent 执行。用于需要专业能力的复杂任务。"""
        if agent_name not in _agents:
            return {"success": False, "error": f"Agent '{agent_name}' 未注册"}

        agent = _agents[agent_name]
        log.info("委派任务给 %s: %s", agent_name, task[:100])

        try:
            # 构建子 Agent 的输入消息
            from langchain_core.messages import SystemMessage, HumanMessage
            from langgraph.checkpoint.memory import MemorySaver

            sub_checkpoint = MemorySaver()
            sub_graph = agent.get_graph()
            sub_config = {"configurable": {"thread_id": f"sub_{agent_name}_{id(task)}"}}

            # 注入系统提示
            system_prompt = agent.get_system_prompt()
            if context:
                system_prompt += f"\n\n## 额外上下文\n{context}"

            sub_graph.update_state(sub_config, {
                "messages": [SystemMessage(content=system_prompt)]
            })

            # 执行子 Agent
            result_messages = []
            events = sub_graph.stream(
                {"messages": [HumanMessage(content=task)]},
                sub_config,
                stream_mode=["updates"],
            )

            for mode, data in events:
                if mode == "updates":
                    # 收集 agent 节点的输出
                    if "agent" in data:
                        agent_msg = data["agent"].get("messages")
                        if agent_msg:
                            msgs = agent_msg if isinstance(agent_msg, list) else [agent_msg]
                            for msg in msgs:
                                if hasattr(msg, 'content') and msg.content:
                                    result_messages.append(msg.content)

            result = "\n".join(result_messages) if result_messages else "子 Agent 未产生输出"
            log.info("子 Agent %s 完成: %s", agent_name, result[:200])
            return {"success": True, "agent": agent_name, "result": result}

        except Exception as e:
            log.error("子 Agent %s 执行失败: %s", agent_name, e)
            return {"success": False, "error": str(e)}

    delegate.__name__ = tool_name
    delegate.__doc__ = f"将任务委派给{agent_desc}执行。适用于需要{agent_desc}的场景。"
    return delegate


# 预定义的委托工具工厂
def create_delegate_tools() -> list:
    """创建所有委托工具（需要先调用 init_delegate_tools 注入 Agent）"""
    return [
        _make_delegate_tool("code", "代码工程师：编写、修改、调试代码"),
        _make_delegate_tool("research", "代码研究员：搜索、阅读、分析代码库"),
        _make_delegate_tool("review", "代码审查员：审查代码质量、安全性"),
    ]
