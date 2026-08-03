"""Tests for Claude Desktop support in ``nlm setup add/remove/list``."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from notebooklm_tools.cli.commands.setup import (
    CLIENT_REGISTRY,
    MCP_SERVER_CMD,
    _claude_desktop_config_path,
    _detect_tool,
    _is_already_configured,
    _remove_single,
    _setup_claude_desktop,
)


class TestClaudeDesktopRegistry:
    """Verify Claude Desktop is properly registered in CLIENT_REGISTRY."""

    def test_claude_desktop_in_registry(self):
        assert "claude-desktop" in CLIENT_REGISTRY

    def test_claude_desktop_has_auto_setup(self):
        assert CLIENT_REGISTRY["claude-desktop"]["has_auto_setup"] is True

    def test_claude_desktop_name(self):
        assert CLIENT_REGISTRY["claude-desktop"]["name"] == "Claude Desktop"


class TestClaudeDesktopConfigPath:
    """Verify platform-specific config path resolution."""

    def test_macos_path(self):
        with patch("platform.system", return_value="Darwin"):
            path = _claude_desktop_config_path()
        assert path == (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )

    def test_windows_path(self):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict("os.environ", {"APPDATA": "C:/Users/test/AppData/Roaming"}),
        ):
            path = _claude_desktop_config_path()
        assert (
            path == Path("C:/Users/test/AppData/Roaming") / "Claude" / "claude_desktop_config.json"
        )

    def test_windows_path_falls_back_when_appdata_is_missing(self):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(os.environ, {}, clear=True),
        ):
            path = _claude_desktop_config_path()
        assert path == Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"

    def test_windows_path_uses_existing_msix_config(self, tmp_path):
        local_app_data = tmp_path / "LocalAppData"
        msix_config = (
            local_app_data
            / "Packages"
            / "Claude_pzs8sxrjxfjjc"
            / "LocalCache"
            / "Roaming"
            / "Claude"
            / "claude_desktop_config.json"
        )
        msix_config.parent.mkdir(parents=True)
        msix_config.write_text("{}")

        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {
                    "APPDATA": str(tmp_path / "AppData" / "Roaming"),
                    "LOCALAPPDATA": str(local_app_data),
                },
            ),
        ):
            path = _claude_desktop_config_path()
        assert path == msix_config

    def test_windows_path_uses_standard_path_when_msix_install_is_ambiguous(self, tmp_path):
        local_app_data = tmp_path / "LocalAppData"
        for package_name in ("Claude_first", "Claude_second"):
            (local_app_data / "Packages" / package_name).mkdir(parents=True)

        appdata = tmp_path / "AppData" / "Roaming"
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {"APPDATA": str(appdata), "LOCALAPPDATA": str(local_app_data)},
            ),
        ):
            path = _claude_desktop_config_path()
        assert path == appdata / "Claude" / "claude_desktop_config.json"

    def test_linux_path(self):
        with patch("platform.system", return_value="Linux"):
            path = _claude_desktop_config_path()
        assert path == Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


class TestSetupClaudeDesktop:
    """Test ``_setup_claude_desktop()`` writes the correct config format."""

    def test_creates_config_with_full_binary_path(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
                return_value=config_path,
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
        ):
            result = _setup_claude_desktop()

        assert result is True
        config = json.loads(config_path.read_text())
        assert "notebooklm-mcp" in config["mcpServers"]
        entry = config["mcpServers"]["notebooklm-mcp"]
        assert entry["command"] == "/usr/local/bin/notebooklm-mcp"
        assert entry["args"] == []

    def test_returns_false_without_writing_when_binary_is_not_on_path(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
                return_value=config_path,
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value=None,
            ),
        ):
            result = _setup_claude_desktop()

        assert result is False
        assert not config_path.exists()

    def test_preserves_existing_config_keys(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        existing = {
            "mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}},
            "coworkUserFilesPath": "/Users/test/Claude",
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing))

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
                return_value=config_path,
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
        ):
            _setup_claude_desktop()

        config = json.loads(config_path.read_text())
        assert config["coworkUserFilesPath"] == existing["coworkUserFilesPath"]
        assert "fetch" in config["mcpServers"]
        assert "notebooklm-mcp" in config["mcpServers"]

    def test_skips_if_already_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {"mcpServers": {"notebooklm-mcp": {"command": "/usr/local/bin/notebooklm-mcp"}}}
            )
        )

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            result = _setup_claude_desktop()

        assert result is True


class TestIsAlreadyConfigured:
    """Test ``_is_already_configured()`` for Claude Desktop."""

    def test_detects_notebooklm_key(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"mcpServers": {"notebooklm": {"command": MCP_SERVER_CMD}}})
        )
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("claude-desktop") is True

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"mcpServers": {}}))
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("claude-desktop") is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("claude-desktop") is False


class TestDetectTool:
    """Test ``_detect_tool()`` for Claude Desktop."""

    def test_detects_via_config_directory(self, tmp_path):
        config_path = tmp_path / "Claude" / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            assert _detect_tool("claude-desktop") is True

    def test_not_detected_when_absent(self, tmp_path):
        config_path = tmp_path / "Claude" / "claude_desktop_config.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            assert _detect_tool("claude-desktop") is False


class TestRemoveClaudeDesktop:
    """Test ``_remove_single()`` for Claude Desktop."""

    def test_removes_notebooklm_entry(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config = {
            "coworkUserFilesPath": "/Users/test/Claude",
            "mcpServers": {
                "notebooklm-mcp": {"command": "/usr/local/bin/notebooklm-mcp", "args": []},
                "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
            },
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            result = _remove_single("claude-desktop")

        assert result is True
        updated = json.loads(config_path.read_text())
        assert "notebooklm-mcp" not in updated["mcpServers"]
        assert "fetch" in updated["mcpServers"]
        assert updated["coworkUserFilesPath"] == config["coworkUserFilesPath"]

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"mcpServers": {}}))

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            result = _remove_single("claude-desktop")

        assert result is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_config_path",
            return_value=config_path,
        ):
            result = _remove_single("claude-desktop")

        assert result is False
