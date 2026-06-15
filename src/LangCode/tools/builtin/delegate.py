"""delegate 工具 — 子 Agent 委派工具。

LLM 通过 tool calling 调用 delegate_explore / delegate_review 触发子 Agent。
router.process_tool_results() 识别 delegate_* 前缀 → 设置 route + task_description。
graph_builder 的 delegate_router 节点构建子 Agent 输入消息。

与 Claude Code AgentTool 同理念：
  工具本身只返回成功 JSON，真正的子图执行由 LangGraph 图路由完成。
  原因：LangChain tool 无法直接修改 LangGraph 状态。
"""

from langchain.tools import tool
from pydantic import BaseModel, Field

from LangCode.shared.logger import get_logger

log = get_logger("tools.delegate")


class DelegateTaskInput(BaseModel):
    task: str = Field(
        description="任务描述，应包含足够的上下文信息让子 Agent 独立完成任务，"
                    "包括：目标、涉及的文件/目录、需要关注的要点。"
    )


@tool("delegate_explore", args_schema=DelegateTaskInput)
def delegate_explore(task: str) -> str:
    """将代码搜索任务委派给 Explore Agent。

    适用场景：
    - 需要跨多个文件搜索、阅读和分析的任务
    - 查找特定代码模式、函数定义、用法
    - 理解项目结构、模块关系
    - 分析代码变更历史

    不适用：
    - 简单的单文件读取（直接用 read_file）
    - 代码修改任务（这不是只读 Agent 的职责）
    - 代码审查（用 delegate_review）
    """
    log.info("delegate_explore: task=%s", task[:100])
    import json
    return json.dumps(
        {"agent": "explore", "task": task, "status": "delegated"},
        ensure_ascii=False,
    )


@tool("delegate_review", args_schema=DelegateTaskInput)
def delegate_review(task: str) -> str:
    """将代码审查任务委派给 Review Agent。

    适用场景：
    - 代码质量审查
    - 安全性分析
    - Bug 发现
    - 代码风格和最佳实践检查

    不适用：
    - 简单的代码阅读（直接用 read_file）
    - 代码修改任务（Review Agent 只读）
    - 代码搜索（用 delegate_explore）
    """
    log.info("delegate_review: task=%s", task[:100])
    import json
    return json.dumps(
        {"agent": "review", "task": task, "status": "delegated"},
        ensure_ascii=False,
    )


delegate_tools = [delegate_explore, delegate_review]
