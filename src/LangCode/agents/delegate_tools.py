"""多 Agent 委托工具：工厂模式创建，避免全局变量注入"""

from langchain.tools import tool
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from LangCode.shared.logger import get_logger

log = get_logger("agents.delegate")

# 每个子 Agent 的 checkpoint 缓存，避免每次调用都创建新实例
_sub_checkpoints: dict[str, MemorySaver] = {}


def _get_sub_checkpoint(agent_name: str) -> MemorySaver:
    """获取或创建子 Agent 的 checkpoint（每个 agent 只创建一次）"""
    if agent_name not in _sub_checkpoints:
        _sub_checkpoints[agent_name] = MemorySaver()
    return _sub_checkpoints[agent_name]


class DelegateInput(BaseModel):
    task: str = Field(description="要委派给子 Agent 的具体任务描述")
    context: str = Field(default="", description="额外的上下文信息")


def _make_delegate_tool(agent_name: str, agent_desc: str, agents: dict):
    """动态创建委托工具，通过参数注入 agents 而非全局变量"""

    @tool(f"delegate_to_{agent_name}", args_schema=DelegateInput, return_direct=True)
    def delegate(task: str, context: str = "") -> dict:
        """将任务委派给指定的专业 Agent 执行。用于需要专业能力的复杂任务。"""
        if agent_name not in agents:
            return {"success": False, "error": f"Agent '{agent_name}' 未注册"}

        agent = agents[agent_name]
        log.info("委派任务给 %s: %s", agent_name, task[:100])

        try:
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

    delegate.__name__ = f"delegate_to_{agent_name}"
    delegate.__doc__ = f"将任务委派给{agent_desc}执行。适用于需要{agent_desc}的场景。"
    return delegate


def create_delegate_tools(agents: dict) -> list:
    """创建所有委托工具

    Args:
        agents: {"code": CodeAgent, "research": ResearchAgent, "review": ReviewAgent}
    """
    return [
        _make_delegate_tool("code", "代码工程师：编写、修改、调试代码", agents),
        _make_delegate_tool("research", "代码研究员：搜索、阅读、分析代码库", agents),
        _make_delegate_tool("review", "代码审查员：审查代码质量、安全性", agents),
    ]
