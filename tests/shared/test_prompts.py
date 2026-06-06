"""shared/test_prompts.py — get_platform_prompt 测试"""

from unittest.mock import patch

from LangCode.shared.prompts import get_platform_prompt


class TestGetPlatformPrompt:
    def test_contains_agent_name(self):
        result = get_platform_prompt()
        assert "LangCode" in result

    def test_contains_python_version(self):
        result = get_platform_prompt()
        import platform
        assert platform.python_version() in result

    def test_contains_os_info(self):
        result = get_platform_prompt()
        # 应包含安全准则
        assert "安全准则" in result

    @patch("LangCode.shared.prompts._platform")
    def test_windows_os(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        mock_platform.python_version.return_value = "3.11.0"
        result = get_platform_prompt()
        assert "windows" in result

    @patch("LangCode.shared.prompts._platform")
    def test_darwin_becomes_mac(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_platform.python_version.return_value = "3.11.0"
        result = get_platform_prompt()
        assert "mac" in result

    @patch("LangCode.shared.prompts._platform")
    def test_linux_os(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        mock_platform.python_version.return_value = "3.11.0"
        result = get_platform_prompt()
        assert "linux" in result
