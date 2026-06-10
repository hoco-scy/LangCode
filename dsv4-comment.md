# LangCode v3 深度评估报告

> v2 评估后实现了 9 个提交，修复了所有 P0 bug 和大部分 P1 问题。
> 测试 169 个全部通过，源码 ~3,518 行，工具 25+ 个。
> 本报告基于当前代码进行第三次全面审查。

---

## 总体评语

**v3 是一个显著成熟的版本。** v2 指出的 5 个 P0 correctness bug 全部修复，主要的架构债务（nest_asyncio、type() 动态类、子 Agent 能力不平等）已清理。代码从 "能用但粗糙" 提升到了 "工程上合理、简历上可以自信展示" 的水平。

但仍有几个问题值得关注：**SupervisorAgent 和 BaseAgent 的 context management 逻辑完全重复**、`should_continue_plan` 是有测试但从未被图使用的死代码、以及一些命名和风格的不一致。

---

## 1. v2 → v3 已修复问题清单

### P0 — 全部修复
| 问题 | 状态 |
|------|:---:|
| `fetch_api` 丢失响应内容 | ✅ 新增 `FetchAPIResponse`，包含 `content` 和 `status_code` |
| `ast_add_method` 插入行号错误 | ✅ `insert_line = body.end_point[0] + 2` |
| CodeAgent verify 路由字符串匹配 | ✅ 改为 `state.get("verify_errors")` 条件判断 |
| CodeAgent `_tools_routing` 死代码 | ✅ 已删除 |
| 空残留文件（supervisor/tools.py, shared/nodes.py） | ✅ 已删除 |

### P1 — 大部分修复
| 问题 | 状态 |
|------|:---:|
| 子 Agent 无上下文管理 | ✅ BaseAgent._call_llm 提供 trim + summarize + memory injection |
| ResearchAgent 无专业化流程 | ✅ 添加 synthesize → synthesize_llm 报告生成管道 |
| ReviewAgent report 阶段绑定工具 | ✅ 使用 `self.llm`（raw LLM）生成报告，防止幻觉 tool_calls |
| 子 Agent 结果纯文本 | ✅ 返回结构化 `{success, summary, tool_calls, files_modified}` |
| ast_tools.py 6 处重复 converter | ✅ EditResult.to_dict() 消除重复 |
| token 估算纯启发式 | ✅ 优先使用 tiktoken (cl100k_base)，回退到 CJK 感知启发式 |
| MCP nest_asyncio hack | ✅ 改为独立线程 + asyncio.run() |
| MCP type() 动态类 | ✅ 改为 pydantic.create_model() |
| main.py 工具组合"大杂烩" | ✅ 提取 create_agent() 工厂函数 |
| MCP 连接在 import 时触发 | ✅ 移入 create_agent() 内部 |
| tools.py import 结构混乱 | ✅ import 移至文件顶部 |
| git_blame porcelain 解析脆弱 | ✅ `isalnum()` → hex 字符精确匹配 |

---

## 2. 逐模块审查（当前状态）

### 2.1 `shared/schemas.py` — 结构化响应模型

**评价：功能完整，有轻微技术债。**

- 13 个 Pydantic 模型覆盖所有工具响应
- `FetchAPIResponse` 解决了最大的回归 bug
- `ToolResponse.__getitem__/get/__contains__` 兼容层仍然存在 — 这是为了支持旧代码的 `result["key"]` 访问。可以逐步移除，但当前无危害
- `GitBlameEntry` 字段命名仍然不理想：`reference` 存的是 "author: summary" 拼接字符串，`lines` 是行数。建议拆分为 `author: str`, `summary: str`, `line_count: int`

### 2.2 `shared/tools.py` — 核心工具集

**评价：11 个工具，质量稳定。**

- `fetch_api` 回归已修复，现在返回完整的 `FetchAPIResponse`
- `git_blame` porcelain 解析改为 hex 字符精确匹配
- `_extract_user_error` 使用 `str | None` 语法，与项目其他地方 `Optional[str]` 不一致，但功能正确
- import 结构已整理干净
- Python 沙箱设计合理：wrapper 注入 + watchdog + 独立进程

### 2.3 `shared/ast_editor.py` — AST 编辑器

**评价：工程上 80 分，核心算法正确。**

- `EditResult.to_dict()` 消除了下游重复
- `ast_add_method` 插入行号修复为 `body.end_point[0] + 2`
- `_find_assignments` 提升为模块级函数
- **仍存在的限制**：`ast_rename` 通过 `_find_all_identifiers` 查找所有同名标识符，不进行作用域分析。在单函数内重命名局部变量是安全的（通常 LLM 一次只编辑一个文件），但跨函数重命名同名参数会误伤。实现完整的作用域树需要遍历 tree-sitter 的 parent 链，是显著的工作量
- 仍然只支持 Python（`SUPPORTED_EXTENSIONS = {".py"}`），架构上通过懒加载 parser 字典可以轻松扩展

### 2.4 `shared/ast_tools.py` — AST 工具包装

**评价：简洁，合格。**

- import 已从函数体内移到文件顶部
- 所有 EditResult-returning 工具使用 `.to_dict()`
- `ast_info` 和 `ast_find` 仍然返回原始 dict（因为它们不是 EditResult）— 这是合理的，因为它们的返回结构不同

### 2.5 `shared/context.py` — 上下文窗口管理

**评价：v3 最干净的模块之一。**

- tiktoken 优先，回退启发式，逻辑清晰
- CJK 检测覆盖了基本区（`一`-`鿿`）和扩展 A 区（`㐀`-`䶿`）
- `trim_messages` 策略正确：保留 SystemMessage → 保留最近消息 → 裁剪中间 → 插入通知
- `summarize_old_messages` 在超过 85% 阈值时触发 LLM 摘要，失败时回退到裁剪
- **常量硬编码**：`DEFAULT_MAX_TOKENS = 80_000` 对 GPT-4 合理，对 Claude 200K 浪费空间，对 DeepSeek 32K 会超限。生产环境应从 model config 读取

### 2.6 `shared/mcp_client.py` — MCP 集成

**评价：架构改进显著，质量提升。**

- `_run_async` 改为线程方案，移除了 nest_asyncio 依赖
- `create_model()` 替代了 `type()` hack
- JSON Schema 类型映射仍然不完整（不支持 array/object/enum/$ref），但对大多数 MCP 工具够用
- 没有连接断开检测和重连机制
- MCP 工具调用无结果大小限制

### 2.7 `agents/base.py` — Agent 基类

**评价：v3 最重要的架构改进，DRY 了核心能力。**

- `_call_llm` 统一提供：retry 保护 → trim → summarize → memory injection → LLM 调用
- 所有子 Agent（CodeAgent、ResearchAgent、ReviewAgent）通过继承获得这些能力
- 默认 `build_graph()` 提供标准 ReAct 循环，子类可按需覆盖

### 2.8 `agents/supervisor/graph.py` — SupervisorAgent

**评价：功能最强但也最需要重构的模块。**

**P0 — SupervisorAgent 和 BaseAgent 的 `_call_llm` 逻辑完全重复**

`supervisor/graph.py:_call_llm`（模块级函数）和 `BaseAgent._call_llm`（方法）包含几乎相同的代码：
- 重试上限检查（lines 41-46 vs base.py:52-57）
- trim_messages + summarize_old_messages（lines 49-50 vs base.py:60-62）
- memory_context 注入（lines 53-62 vs base.py:66-74）

唯一的区别是 SupervisorAgent 多了 plan summary 注入（lines 65-76）。这意味着每次修改 context management 逻辑都需要改两个地方。

**修复建议**：让 SupervisorAgent 继承 BaseAgent，覆盖 `_call_llm` 调用 `super()._call_llm()` 并追加 plan 注入。或者至少把共享逻辑提取到一个独立函数。

**P1 — SystemMessage 检测方式不一致**
```python
# supervisor/graph.py:57
if hasattr(m, 'type') and m.type == 'system':

# base.py:69  
if isinstance(m, SystemMessage):
```
`isinstance` 更 Pythonic 且更可靠（不依赖字符串比较）。

**P2 — SupervisorAgent 未继承 BaseAgent**
SupervisorAgent 是独立的类，不继承 BaseAgent。这意味着它不能复用 BaseAgent 的工具描述方法、图编译逻辑等。如果改为继承 BaseAgent，只需覆盖 `build_graph()` 和 `_call_llm()`。

### 2.9 `agents/code_agent/graph.py` — CodeAgent

**评价：write→verify→fix 闭环工作正常，控制流干净。**

- `_verify_routing` 改用 `state.get("verify_errors")` 而不是字符串匹配
- `_run_import_check` 改用 `sys.path.insert(0, project_root) + __import__(mod_path)`
- 死代码 `_tools_routing` 已删除
- `_find_test_files` 路径猜测仍然 heuristic，但覆盖率比之前好

### 2.10 `agents/research_agent/graph.py` — ResearchAgent

**评价：终于有了真正的专业化流程。**

- 图结构：agent → tools → agent → ... → synthesize → synthesize_llm → END
- `_synthesize_node` 注入报告生成指令
- `_agent_routing` 第一次无工具调用就进入 synthesize — 如果 LLM 一次工具都不调用，会直接生成报告。prompt 中写了"多轮收集"，但图结构不强制执行。建议加一个 `research_rounds` 计数器
- 这个缺点在实际使用中影响不大 — LLM 通常会用工具

### 2.11 `agents/review_agent/graph.py` — ReviewAgent

**评价：设计最完善的专业 Agent。**

- 使用 `self.llm`（raw LLM）生成报告，防止幻觉 tool_calls
- `_agent_routing` 有 `MIN_REVIEW_ROUNDS = 1` 计数器，至少一轮工具调用后进入报告
- `_report_node` 合并了之前的两个节点，图结构简洁
- 4 个节点：agent → tools → agent → ... → report → END

### 2.12 `agents/delegate_tools.py` — 委托工具

**评价：结构化结果 + 持久化 thread_id 是正确的方向。**

- 返回 `{success, agent, summary, tool_calls, files_modified}` — Supervisor 可以做更好的决策
- thread_id 固定为 `f"sub_{agent_name}"` — 子 Agent 在多次委派间保持对话记忆
- 子 Agent 结果收集覆盖了 "agent"、"synthesize_llm"、"report" 节点
- summary 截断到 3000 字符

### 2.13 `planning/` — 规划系统

**评价：功能框架完整，但有一个 dead code 问题。**

**P1 — `should_continue_plan` 是死代码**

`planning/reflector.py:89-113` 的 `should_continue_plan` 函数有完整的测试覆盖，但在实际的图定义中从未被使用。SupervisorAgent 的图（`supervisor/graph.py`）使用 `_plan_or_end` 来做路由，而不是 `should_continue_plan`。

它被 `planning/__init__.py` 导出，所以如果外部代码使用了它，它就有存在的价值。但从当前代码库看，没有图节点引用它。

**修复建议**：可以删除，或者用它替换 `_plan_or_end` 以统一路由逻辑。

**其他观察**：
- `plan_show` 仍然是轻量实现（解析 + 格式化），但功能上是正确的
- planner/executor/reflector 三节点配合良好
- Plan/PlanStep Pydantic 模型设计合理

### 2.14 `memory/tools.py` — 记忆工具

**评价：工厂模式好，但 Pydantic 模型位置不对。**

**P1 — Pydantic 模型定义在工厂函数内部**

`MemorySaveInput`、`MemorySearchInput`、`MemoryListInput` 三个类在 `create_memory_tools()` 内部定义。每次调用时重新定义。应该移到模块级别。

**P1 — 仍然返回 dict 而不是 Pydantic 模型**

记忆工具返回的是 `{"success": True, ...}` dict，而其他工具现在返回 Pydantic 模型。与其他工具风格不一致。

### 2.15 `main.py` — 入口

**评价：模块化改进明显。**

- `create_agent()` 工厂函数集中管理所有子系统初始化
- MCP 连接不再在 import 时触发
- `deal_command` 接收显式参数而非全局变量
- `_consume_events` 仍然复杂（嵌套 while+for+if+break），难以测试

---

## 3. 跨模块问题

### 3.1 SupervisorAgent 与 BaseAgent 的关系

当前 SupervisorAgent 是独立类，BaseAgent 是 ABC。它们的 `_call_llm` 有大量重复代码。理想状态是 SupervisorAgent 继承 BaseAgent，覆盖 graph 构建和 LLM 调用。

### 3.2 子 Agent 能力对比（v3）

| 能力 | SupervisorAgent | CodeAgent | ResearchAgent | ReviewAgent |
|------|:---:|:---:|:---:|:---:|
| 上下文窗口管理 | ✓ | ✓ (via BaseAgent) | ✓ (via BaseAgent) | ✓ (via BaseAgent) |
| 记忆上下文注入 | ✓ | ✓ (via BaseAgent) | ✓ (via BaseAgent) | ✓ (via BaseAgent) |
| 计划摘要注入 | ✓ | ✗ | ✗ | ✗ |
| 工具重试上限提示 | ✓ | ✓ (via BaseAgent) | ✓ (via BaseAgent) | ✓ (via BaseAgent) |
| 专业化流程 | N/A | ✓ (verify) | ✓ (synthesize) | ✓ (report) |

v2 中的"子 Agent 能力不平等"问题已解决。上下文管理和记忆注入现在统一由 BaseAgent 提供。

### 3.3 异常处理风格

- `ast_editor.py`：返回 `EditResult(success=False, error=str(e))`
- `mcp_client.py`：返回 `{"success": False, "error": str(e)}`
- `tools.py`：返回 typed response model（如 `FetchAPIResponse(success=False, error=str(e))`）
- `context.py:174`：`except Exception: 回退到裁剪`
- `memory/tools.py`：返回 `{"success": False, "error": str(e)}`

风格不统一但功能正确。建议最终统一为 typed response model。

### 3.4 没有集成测试

169 个测试全是单元测试。没有一个验证完整 agent 流程的集成测试。

---

## 4. 各项指标

| 指标 | v1 | v2 | v3 |
|------|:---:|:---:|:---:|
| 源码行数 | ~2,066 | ~2,900 | ~3,518 |
| 测试数量 | 122 | 169 | 169 |
| 工具数量 | 7 | 16 | 25+ |
| P0 bug | 4 | 5 | 0 |
| P1 问题 | ~15 | ~13 | ~4 |
| 空残留文件 | 2 | 2 | 0 |

---

## 5. 当前问题优先级

### 建议修复（P1）

1. **SupervisorAgent 继承 BaseAgent** — 消除 `_call_llm` 重复（约 40 行重复代码），统一 SystemMessage 检测方式
2. **删除 `should_continue_plan` 或用它替换 `_plan_or_end`** — 清理死代码
3. **`memory/tools.py` Pydantic 模型移到模块级别** — 避免重复定义
4. **`GitBlameEntry` 拆分字段** — `reference` → `author` + `summary`，`lines` → `line_count`

### 锦上添花（P2）

5. **`_consume_events` 拆分为独立函数** — 提升可测试性
6. **添加端到端集成测试** — 至少一个完整流程
7. **AST 编辑器语言扩展架构** — 懒加载 parser 字典
8. **`plan_show` 与图状态交互** — 从 state 读取而非参数传入
9. **统一工具返回类型** — 全部使用 Pydantic 模型
10. **上下文常量从 model config 读取** — 避免硬编码 80K

---

## 6. 简历适用性评估（更新）

### 现在可以自信地写在简历上了

v3 修复了所有 correctness bug，补齐了架构短板。面试官追问时你能回答的深度问题：

| 面试官可能问 | 你的回答质量 |
|-------------|:----------:|
| "AST 编辑怎么实现的？" | ✅ tree-sitter 字节级编辑，6 种操作，从后往前替换避免偏移 |
| "子 Agent 怎么协作的？" | ✅ Supervisor 通过 delegate tools 委派，结构化结果，持久化 thread_id |
| "上下文窗口怎么管理的？" | ✅ tiktoken 精确计数 + trim + summarize，所有子 Agent 统一获得 |
| "MCP 怎么集成的？" | ✅ stdio 传输，线程桥接 async，pydantic.create_model 动态工具 |
| "代码验证怎么做的？" | ✅ write→verify→fix 闭环，语法→导入→测试三层检查 |
| "ast_rename 的作用域怎么处理？" | ⚠️ 能解释当前限制和 tree-sitter parent 链的改进方向 |
| "SupervisorAgent 和 BaseAgent 的关系？" | ⚠️ 当前独立实现，有重复代码，计划继承 BaseAgent |

**建议**：修完上面 4 个 P1 项后，所有常见追问都能回答得漂亮。

---

## 总结

v3 是一个值得在简历上展示的项目。它从一个 LangGraph 教程集合演变为一个有真正技术含量的 code agent。核心亮点（AST 编辑、多 Agent 协作、上下文管理、MCP 集成）已经足够支撑面试中的深入讨论。剩下的 4 个 P1 问题是 polish 层面的，不影响核心价值。
