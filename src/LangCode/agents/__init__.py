"""agents — 多 Agent 协作系统（v2 重组）

v2 变更：
- AgentDefinition: 声明式 Agent 定义（替代 BaseAgent）
- router: 路由决策（替代 supervisor/router.py）
- verify: auto_verify 自动验证（替代 code_agent 的 verify 节点）
- prompts: 提示词模板加载器（替代 supervisor/prompts.py）
- builtin/: 内置 Agent 子图（explore, review）
- skills/: Skill 系统
"""
