"""已废弃：规划相关工具

plan_create 工具已重构为图节点（planner node），
不再通过工具触发，而是由 supervisor 中枢路由决定进入 plan 路径。

参见: LangCode.planning.planner.create_plan_node
参见: LangCode.agents.supervisor.router
"""

# 此文件已废弃，保留仅为向后兼容提示
# 实际规划逻辑在 planning/planner.py 的 create_plan_node 中
