"""engine.budget — Token 预算追踪器测试"""

import pytest
from LangCode.engine.budget import BudgetTracker, COMPLETION_THRESHOLD, DIMINISHING_THRESHOLD, MIN_CONTINUATIONS


class TestBudgetTracker:
    def test_below_threshold_when_no_budget(self):
        t = BudgetTracker()
        assert t.check(1000, budget=None) == "below_threshold"

    def test_below_threshold_when_zero_budget(self):
        t = BudgetTracker()
        assert t.check(1000, budget=0) == "below_threshold"

    def test_below_threshold_when_agent_id(self):
        """子 Agent 不参与 Token 预算"""
        t = BudgetTracker()
        assert t.check(100_000, budget=50_000, agent_id="explore") == "below_threshold"

    def test_continue_when_under_budget(self):
        t = BudgetTracker()
        budget = 100_000
        # 使用 < 90% → continue
        result = t.check(50_000, budget=budget)
        assert result == "continue"

    def test_stop_when_over_90_percent(self):
        t = BudgetTracker()
        budget = 100_000
        result = t.check(95_000, budget=budget)
        assert result == "stop"

    def test_continue_increments_continuation_count(self):
        t = BudgetTracker()
        t.check(10_000, budget=100_000)
        assert t.continuation_count == 1
        t.check(20_000, budget=100_000)
        assert t.continuation_count == 2

    def test_diminishing_returns_detection(self):
        """连续 3+ 次 + 增量 < 500 → 收益递减 → stop"""
        t = BudgetTracker()
        budget = 100_000

        # 先积累 continuation_count 到 MIN_CONTINUATIONS
        for _ in range(MIN_CONTINUATIONS):
            t.check(10_000, budget=budget)

        # 现在模拟收益递减：delta < 500
        t.last_delta_tokens = 100
        t.last_global_tokens = 10_100
        result = t.check(10_200, budget=budget)  # delta = 100 < 500
        assert result == "stop"

    def test_not_diminishing_if_delta_large(self):
        """增量 > 500 → 不是收益递减"""
        t = BudgetTracker()
        budget = 100_000

        for _ in range(MIN_CONTINUATIONS):
            t.check(10_000, budget=budget)

        t.last_delta_tokens = 1000
        t.last_global_tokens = 10_000
        result = t.check(15_000, budget=budget)  # delta = 5000 > 500
        assert result == "continue"

    def test_state_persists_across_checks(self):
        t = BudgetTracker()
        budget = 100_000

        t.check(10_000, budget=budget)
        t.check(20_000, budget=budget)
        assert t.last_global_tokens == 20_000
        assert t.last_delta_tokens == 10_000
