"""ReviewAgent：专注于代码审查、安全分析、质量评估"""

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Checkpointer

from LangCode.shared.logger import get_logger
from LangCode.agents.base import BaseAgent

log = get_logger("agents.review")

REVIEW_AGENT_PROMPT = """你是一个专业的代码审查 Agent。

## 职责
- 审查代码质量、可读性、可维护性
- 发现潜在的 bug 和安全漏洞
- 评估代码是否符合最佳实践
- 提供改进建议

## 工作方式
1. 阅读目标代码
2. 分析代码结构、逻辑、安全性
3. 生成结构化的审查报告

## 可用工具
- `read_file` — 读取文件内容
- `search_files` — 搜索相关文件
- `run_python` — 运行代码验证行为
- `execute_shell` — 执行 shell 命令（如 linter）

## 审查维度
- **正确性**: 逻辑是否正确，边界条件是否处理
- **安全性**: 是否有注入、越权、信息泄露风险
- **可读性**: 命名、结构、注释是否清晰
- **性能**: 是否有明显的性能问题
- **可维护性**: 是否易于修改和扩展

## 输出格式
审查完成后，输出结构化报告：
```
## 审查报告

### 总体评价
[一句话总结]

### 发现的问题
1. [严重程度: 高/中/低] [文件:行号] [问题描述]
   建议: [改进建议]

### 优点
- [值得肯定的地方]

### 建议
- [总体改进建议]
```
"""


class ReviewAgent(BaseAgent):
    name = "review"
    description = "代码审查员：审查代码质量、安全性，发现 bug，提供改进建议"

    def __init__(self, llm: ChatOpenAI, checkpoint: Checkpointer, tools: list[BaseTool]):
        super().__init__(llm, checkpoint, tools)

    def get_system_prompt(self) -> str:
        return REVIEW_AGENT_PROMPT
