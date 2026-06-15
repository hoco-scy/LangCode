"""services.analytics — AnalyticsTracker 测试"""

import time
import pytest
from LangCode.services.analytics import AnalyticsTracker, init_analytics, get_analytics


@pytest.fixture
def tracker():
    return AnalyticsTracker()


class TestAnalyticsTracker:
    def test_record_startup_phase(self, tracker):
        tracker.record_startup_phase("config_load", 150.0)
        tracker.record_startup_phase("tool_init", 300.0)
        assert len(tracker._startup_phases) == 2
        assert tracker._startup_phases[0].phase == "config_load"
        assert tracker._startup_phases[0].duration_ms == 150.0

    def test_record_api_call(self, tracker):
        tracker.record_api_call(
            model="mimo-v2.5-pro",
            input_tokens=100,
            output_tokens=50,
            duration_ms=500.0,
        )
        assert len(tracker._api_calls) == 1
        assert tracker._total_tokens == 150
        assert tracker._api_calls[0]["model"] == "mimo-v2.5-pro"

    def test_record_api_call_with_cache(self, tracker):
        tracker.record_api_call(model="gpt-4o", input_tokens=200, output_tokens=100, cache_hit=True)
        assert tracker._api_calls[0]["cache_hit"] is True

    def test_record_multiple_api_calls(self, tracker):
        for i in range(5):
            tracker.record_api_call(model="test", input_tokens=10 * i, output_tokens=5 * i)
        assert len(tracker._api_calls) == 5
        assert tracker._total_tokens == sum(10 * i + 5 * i for i in range(5))

    def test_record_tool_call(self, tracker):
        tracker.record_tool_call("read_file", success=True, duration_ms=50.0)
        tracker.record_tool_call("write_file", success=False, duration_ms=100.0)
        assert len(tracker._tool_calls) == 2
        assert tracker._tool_calls[0]["success"] is True
        assert tracker._tool_calls[1]["success"] is False

    def test_record_compact(self, tracker):
        tracker.record_compact("auto", tokens_before=5000, tokens_after=2000, success=True)
        assert len(tracker._compact_events) == 1
        assert tracker._compact_events[0]["tokens_saved"] == 3000

    def test_record_compact_failure(self, tracker):
        tracker.record_compact("auto", 5000, 5000, success=False)
        assert tracker._compact_events[0]["success"] is False

    def test_record_error(self, tracker):
        tracker.record_error("prompt_too_long", recovered=True)
        tracker.record_error("model_unavailable", recovered=False)
        assert len(tracker._error_events) == 2

    def test_time_api_call_context_manager(self, tracker):
        with tracker.time_api_call("test-model") as ctx:
            ctx.record_tokens(input_tokens=100, output_tokens=50)
            time.sleep(0.01)
        assert len(tracker._api_calls) == 1
        assert tracker._api_calls[0]["input_tokens"] == 100
        assert tracker._api_calls[0]["duration_ms"] >= 0

    def test_time_tool_call_context_manager_success(self, tracker):
        with tracker.time_tool_call("read_file"):
            pass  # no exception
        assert len(tracker._tool_calls) == 1
        assert tracker._tool_calls[0]["success"] is True

    def test_time_tool_call_context_manager_failure(self, tracker):
        try:
            with tracker.time_tool_call("write_file"):
                raise ValueError("test error")
        except ValueError:
            pass
        assert len(tracker._tool_calls) == 1
        assert tracker._tool_calls[0]["success"] is False

    def test_time_tool_call_mark_failure(self, tracker):
        with tracker.time_tool_call("edit_file") as ctx:
            ctx.mark_failure()
        assert tracker._tool_calls[0]["success"] is False

    def test_get_snapshot_empty(self, tracker):
        snap = tracker.get_snapshot()
        assert snap["total_api_calls"] == 0
        assert snap["total_tool_calls"] == 0
        assert snap["total_tokens"] == 0
        assert snap["tool_success_rate"] == 0  # 0/0

    def test_get_snapshot_with_data(self, tracker):
        tracker.record_api_call(model="test", input_tokens=100, output_tokens=50)
        tracker.record_tool_call("read_file", success=True)
        tracker.record_tool_call("write_file", success=False)
        tracker.record_error("rate_limit", recovered=True)

        snap = tracker.get_snapshot()
        assert snap["total_api_calls"] == 1
        assert snap["total_tool_calls"] == 2
        assert snap["total_tokens"] == 150
        assert snap["total_errors"] == 1
        assert snap["recovered_errors"] == 1
        assert snap["tool_success_rate"] == 0.5

    def test_get_snapshot_startup_phases(self, tracker):
        tracker.record_startup_phase("init", 100.0)
        tracker.record_startup_phase("load", 200.0)
        snap = tracker.get_snapshot()
        assert len(snap["startup_phases"]) == 2
        assert snap["startup_phases"][0]["phase"] == "init"

    def test_snapshot_has_session_duration(self, tracker):
        snap = tracker.get_snapshot()
        assert "session_duration_s" in snap
        assert snap["session_duration_s"] >= 0


class TestGlobalAnalytics:
    def test_init_and_get(self):
        a1 = init_analytics()
        a2 = get_analytics()
        assert a1 is a2

    def test_get_creates_if_not_initialized(self):
        # get_analytics should auto-init if needed
        a = get_analytics()
        assert a is not None
