"""engine.budget — Token 预算追踪器。

参考 Claude Code checkTokenBudget:
- COMPLETION_THRESHOLD = 0.9 (使用 90% 停止)
- DIMINISHING_THRESHOLD = 500 (增量 < 500 tokens 判定为递减)
- MIN_CONTINUATIONS = 3 (收益递减判定最少检查次数)
- 子Agent (agent_id 非空) 不参与 Token 预算（由 maxTurns 控制）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from LangCode.shared.logger import get_logger

log = get_logger("engine.budget")

# 阈值常量（对齐 Claude Code）
COMPLETION_THRESHOLD: float = 0.9     # 使用 90% 预算 → 停止
DIMINISHING_THRESHOLD: int = 500      # 增量 < 500 tokens → 判定为收益递减
MIN_CONTINUATIONS: int = 3            # 收益递减判定需要最少 3 次 continuation


@dataclass
class BudgetTracker:
    """Token 预算追踪器。

    每次 query_loop 的无工具调用分支（Terminal/Continue 决策点）检查一次。
    收益递减检测：如果连续 >= 3 次增量都 < 500 tokens，说明 LLM 在重复或无意义地继续。
    """
    continuation_count: int = 0
    last_delta_tokens: int = 0
    last_global_tokens: int = 0

    def check(
        self,
        global_tokens: int,
        budget: Optional[int],
        agent_id: Optional[str] = None,
    ) -> str:
        """检查 token 预算。

        Args:
            global_tokens: 累计使用的 token 数
            budget: Token 预算限制（None 表示不限制）
            agent_id: 当前 Agent ID（非空则跳过检查）

        Returns:
            "continue": 可以继续
            "stop": 预算耗尽或收益递减，停止
            "below_threshold": 未到检查阈值，跳过（直接继续）
        """
        # 子Agent 不参与 Token 预算（由 maxTurns 控制）
        if agent_id:
            return "below_threshold"

        if not budget or budget <= 0:
            return "below_threshold"

        delta = global_tokens - self.last_global_tokens

        # 收益递减检测
        is_diminishing = (
            self.continuation_count >= MIN_CONTINUATIONS
            and delta < DIMINISHING_THRESHOLD
            and self.last_delta_tokens < DIMINISHING_THRESHOLD
        )

        if is_diminishing:
            log.info("收益递减: continuation=%d, delta=%d, last_delta=%d",
                     self.continuation_count, delta, self.last_delta_tokens)
            return "stop"

        # 预算使用率检查
        if global_tokens < budget * COMPLETION_THRESHOLD:
            self.continuation_count += 1
            self.last_delta_tokens = delta
            self.last_global_tokens = global_tokens
            pct = round((global_tokens / budget) * 100)
            log.debug("Token 预算: %d/%d (%d%%), continuation=%d",
                      global_tokens, budget, pct, self.continuation_count)
            return "continue"

        log.info("Token 预算耗尽: %d/%d (%d%%)",
                 global_tokens, budget, round((global_tokens / budget) * 100))
        return "stop"
