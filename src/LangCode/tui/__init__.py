"""TUI 模块 - LangCode 的终端用户界面

使用 Textual 框架构建，提供：
- 流式聊天显示
- 工具调用/结果展示
- 中断确认弹窗
- 记忆管理面板
"""

from LangCode.tui.app import LangCodeTUI, run_tui

__all__ = ["LangCodeTUI", "run_tui"]
