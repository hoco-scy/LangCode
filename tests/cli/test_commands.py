"""cli.commands — 斜杠命令处理测试"""

import pytest
from unittest.mock import MagicMock, patch

from LangCode.cli.commands import handle_command


@pytest.fixture
def engine():
    """创建 mock QueryEngine"""
    mock = MagicMock()
    mock.get_current_state.return_value = {
        "messages": [],
        "current_plan": None,
    }
    mock.cfg.memory_store = MagicMock()
    mock.cfg.memory_store.list_all.return_value = []
    mock.cfg.memory_store.count.return_value = 0
    mock.cfg.workspace_dir = "/test/workspace"
    return mock


def _mock_app_state(agent_mode="default"):
    """创建 mock AppState"""
    mock_state = MagicMock()
    mock_state.session.agent_mode = agent_mode
    return mock_state


class TestModeCommand:
    @patch("LangCode.state.app_state.get_app_state", return_value=_mock_app_state("default"))
    def test_mode_status(self, mock_get, engine, capsys):
        result = handle_command(engine, "/mode")
        assert result is True
        captured = capsys.readouterr()
        assert "default" in captured.out

    @patch("LangCode.state.app_state.update_app_state")
    def test_mode_set_plan(self, mock_update, engine, capsys):
        result = handle_command(engine, "/mode plan")
        assert result is True
        mock_update.assert_called_once()

    def test_mode_set_invalid(self, engine, capsys):
        result = handle_command(engine, "/mode invalid")
        assert result is True
        captured = capsys.readouterr()
        assert "无效" in captured.out

    @patch("LangCode.state.app_state.update_app_state")
    def test_mode_set_bypass(self, mock_update, engine, capsys):
        result = handle_command(engine, "/mode bypass")
        assert result is True
        mock_update.assert_called_once()


class TestSessionCommand:
    @patch("LangCode.state.app_state.get_app_state", return_value=_mock_app_state("default"))
    def test_session_info(self, mock_get, engine, capsys):
        result = handle_command(engine, "/session")
        assert result is True
        captured = capsys.readouterr()
        assert "条消息" in captured.out

    @patch("LangCode.state.app_state.get_app_state", return_value=_mock_app_state("default"))
    def test_session_with_plan(self, mock_get, engine, capsys):
        engine.get_current_state.return_value = {
            "messages": [MagicMock()],
            "current_plan": {"goal": "test", "steps": []},
        }
        result = handle_command(engine, "/session")
        assert result is True
        captured = capsys.readouterr()
        assert "计划进行中" in captured.out


class TestPlanCommand:
    def test_no_plan(self, engine, capsys):
        result = handle_command(engine, "/plan")
        assert result is True
        captured = capsys.readouterr()
        assert "没有活跃" in captured.out

    def test_with_plan(self, engine, capsys):
        engine.get_current_state.return_value = {
            "messages": [],
            "current_plan": {
                "goal": "test goal",
                "steps": [
                    {"step_id": 1, "description": "step1", "status": "done"},
                    {"step_id": 2, "description": "step2", "status": "in_progress"},
                ],
                "status": "active",
            },
        }
        result = handle_command(engine, "/plan")
        assert result is True
        captured = capsys.readouterr()
        assert "test goal" in captured.out


class TestMemoryCommand:
    def test_no_memories(self, engine, capsys):
        engine.cfg.memory_store.list_all.return_value = []
        engine.cfg.memory_store.count.return_value = 0
        result = handle_command(engine, "/memory")
        assert result is True
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_no_memory_store(self, engine, capsys):
        engine.cfg.memory_store = None
        result = handle_command(engine, "/memory")
        assert result is True
        captured = capsys.readouterr()
        assert "未初始化" in captured.out

    def test_with_memories(self, engine, capsys):
        mock_record = MagicMock()
        mock_record.memory_type = "user"
        mock_record.tags = ["test"]
        mock_record.content = "test memory content"
        engine.cfg.memory_store.list_all.return_value = [mock_record]
        engine.cfg.memory_store.count.return_value = 1

        result = handle_command(engine, "/memory")
        assert result is True
        captured = capsys.readouterr()
        assert "1 条记忆" in captured.out


class TestSkillsCommand:
    def test_no_skills_dir(self, engine, capsys):
        result = handle_command(engine, "/skills")
        assert result is True
        captured = capsys.readouterr()
        assert "未找到" in captured.out or "内置技能" in captured.out


class TestAnalyticsCommand:
    def test_analytics(self, engine, capsys):
        result = handle_command(engine, "/analytics")
        assert result is True


class TestUnknownCommand:
    def test_unknown_command(self, engine):
        result = handle_command(engine, "/unknown")
        assert result is False
