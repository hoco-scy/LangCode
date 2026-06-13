"""已废弃：多 Agent 委托工具

委托功能已重构为中枢路由节点（supervisor router），
不再通过工具触发，而是由 supervisor 使用 structured output 决定路由。

参见: LangCode.agents.supervisor.router
"""

# 此文件已废弃，保留仅为向后兼容提示
# 实际委托逻辑在 agents/supervisor/router.py 的 supervisor_node 中
