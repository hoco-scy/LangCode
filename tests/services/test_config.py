"""services.config — 分层配置系统测试"""

import pytest
import json
import os
from pathlib import Path
from unittest.mock import patch

from LangCode.services.config import Config, _flatten_dict, CONFIG_DEFAULTS


class TestFlattenDict:
    def test_flat(self):
        assert _flatten_dict({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_nested(self):
        result = _flatten_dict({"model": {"name": "gpt-4", "temperature": 0}})
        assert result == {"model.name": "gpt-4", "model.temperature": 0}

    def test_deep_nested(self):
        result = _flatten_dict({"a": {"b": {"c": 1}}})
        assert result == {"a.b.c": 1}

    def test_mixed(self):
        result = _flatten_dict({"x": 1, "model": {"name": "test"}})
        assert result == {"x": 1, "model.name": "test"}


class TestConfigDefaults:
    def test_defaults_only(self):
        c = Config([CONFIG_DEFAULTS.copy()])
        assert c.get("model.name") == "mimo-v2.5-pro"
        assert c.get("session.max_turns") == 50
        assert c.get("permission.mode") == "default"
        assert c.get("verify.auto_enabled") is True

    def test_get_with_default(self):
        c = Config([CONFIG_DEFAULTS.copy()])
        assert c.get("nonexistent", "fallback") == "fallback"
        assert c.get("nonexistent") is None


class TestConfigLayers:
    def test_higher_overrides_lower(self):
        layers = [
            {"model.name": "default-model"},
            {"model.name": "user-model"},
        ]
        c = Config(layers)
        assert c.get("model.name") == "user-model"

    def test_layer_priority(self):
        layers = [
            {"a": 1, "b": 2, "c": 3},
            {"b": 20},
            {"c": 300},
        ]
        c = Config(layers)
        assert c.get("a") == 1
        assert c.get("b") == 20
        assert c.get("c") == 300


class TestConfigLoad:
    def test_load_with_env_vars(self):
        with patch.dict(os.environ, {"LC_MODEL_NAME": "test-model", "LC_API_KEY": "test-key"}):
            c = Config.load()
            assert c.get("model.name") == "test-model"
            assert c.get("model.api_key") == "test-key"

    def test_load_without_env(self):
        """无环境变量覆盖时使用默认值"""
        with patch.dict(os.environ, {}, clear=False):
            # 移除所有 LC_ 环境变量
            for key in list(os.environ.keys()):
                if key.startswith("LC_"):
                    del os.environ[key]
            c = Config.load()
            assert c.get("model.name") == "mimo-v2.5-pro"


class TestConfigGetModel:
    def test_get_model_returns_all_fields(self):
        c = Config([CONFIG_DEFAULTS.copy()])
        m = c.get_model()
        assert "name" in m
        assert "api_key" in m
        assert "base_url" in m
        assert "temperature" in m
        assert "fallback" in m

    def test_get_permission_mode(self):
        c = Config([CONFIG_DEFAULTS.copy()])
        assert c.get_permission_mode() == "default"

    def test_get_max_turns(self):
        c = Config([{"session.max_turns": 100}])
        assert c.get_max_turns() == 100

    def test_get_token_budget(self):
        c = Config([{"session.token_budget": 50000}])
        assert c.get_token_budget() == 50000

        c2 = Config([CONFIG_DEFAULTS.copy()])
        assert c2.get_token_budget() == 200_000
