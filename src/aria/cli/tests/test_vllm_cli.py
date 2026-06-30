"""Tests for aria vllm CLI commands (install/update/uninstall/restart/etc)."""

from unittest.mock import patch

from typer.testing import CliRunner

from aria.cli.vllm import app

runner = CliRunner()


def _patch_remote(value: bool):
    return patch("aria.config.api.Vllm.remote", value)


class TestRestart:
    """aria vllm restart — stop then start, with remote guard."""

    def test_restart_calls_stop_then_start(self):
        with (
            _patch_remote(False),
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            mgr = MockMgr.return_value
            result = runner.invoke(app, ["restart"])

        assert result.exit_code == 0
        mgr.stop_all.assert_called_once()
        mgr.start_all.assert_called_once()

    def test_restart_in_remote_mode_refuses(self):
        with (
            _patch_remote(True),
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            result = runner.invoke(app, ["restart"])

        assert result.exit_code == 0
        assert "externally managed" in result.output
        MockMgr.assert_not_called()

    def test_restart_reports_failure(self):
        with (
            _patch_remote(False),
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            mgr = MockMgr.return_value
            mgr.stop_all.side_effect = RuntimeError("boom")
            result = runner.invoke(app, ["restart"])

        assert result.exit_code == 1
        assert "Restart failed" in result.output


class TestStart:
    """aria vllm start — remote guard."""

    def test_start_in_remote_mode_refuses(self):
        with (
            _patch_remote(True),
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            result = runner.invoke(app, ["start"])

        assert result.exit_code == 0
        assert "externally managed" in result.output
        MockMgr.assert_not_called()


class TestStop:
    """aria vllm stop — remote guard."""

    def test_stop_in_remote_mode_refuses(self):
        with (
            _patch_remote(True),
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            result = runner.invoke(app, ["stop"])

        assert result.exit_code == 0
        assert "externally managed" in result.output
        MockMgr.assert_not_called()


class TestUpdate:
    """aria vllm update."""

    def test_already_up_to_date_skips_reinstall(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            MockMgr.return_value._pids = {}
            MockMgr._find_orphan_pids.return_value = []
            result = runner.invoke(app, ["update"])

        assert result.exit_code == 0
        assert "already up to date" in result.output
        mock_update.assert_not_called()

    def test_update_new_version_stops_recreates_restarts(self):
        """Newer version + running server → stop, recreate, restart."""
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value="0.25.0"),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            mgr_instance = MockMgr.return_value
            mgr_instance._pids = {"chat": 1234}  # was running
            MockMgr._find_orphan_pids.return_value = []
            result = runner.invoke(app, ["update"])

        assert result.exit_code == 0
        mock_update.assert_called_once_with(version="0.25.0")
        mgr_instance.stop_all.assert_called_once()
        assert "restarted" in result.output

    def test_update_new_version_not_running_no_restart(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value="0.25.0"),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            mgr_instance = MockMgr.return_value
            mgr_instance._pids = {}  # not running
            MockMgr._find_orphan_pids.return_value = []
            result = runner.invoke(app, ["update"])

        assert result.exit_code == 0
        mock_update.assert_called_once_with(version="0.25.0")
        mgr_instance.stop_all.assert_not_called()
        assert "Run: aria vllm start" in result.output

    def test_update_offline_falls_back_to_pinned_version(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value=None),
            patch("aria.config.api.Vllm.version", "0.24.0"),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            MockMgr.return_value._pids = {}
            MockMgr._find_orphan_pids.return_value = []
            result = runner.invoke(app, ["update", "--no-latest"])

        # target == Vllm.version == installed → already up to date
        assert result.exit_code == 0
        assert "already up to date" in result.output
        mock_update.assert_not_called()

    def test_update_remote_refuses(self):
        with (
            _patch_remote(True),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
        ):
            result = runner.invoke(app, ["update"])

        assert result.exit_code == 0
        assert "externally managed" in result.output
        mock_update.assert_not_called()

    def test_update_explicit_version_not_equal_reinstalls(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
            patch("aria.scripts.vllm.update_vllm") as mock_update,
            patch("aria.server.vllm.VllmServerManager") as MockMgr,
        ):
            MockMgr.return_value._pids = {}
            MockMgr._find_orphan_pids.return_value = []
            result = runner.invoke(
                app, ["update", "--version", "0.25.0", "--no-latest"]
            )

        assert result.exit_code == 0
        mock_update.assert_called_once_with(version="0.25.0")


class TestUninstall:
    """aria vllm uninstall / uninstall --legacy."""

    def test_uninstall_calls_uninstall_vllm(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.uninstall_vllm") as mock_uninstall,
            patch("aria.scripts.vllm.uninstall_legacy_vllm") as mock_legacy,
        ):
            result = runner.invoke(app, ["uninstall"])

        assert result.exit_code == 0
        mock_uninstall.assert_called_once()
        mock_legacy.assert_not_called()

    def test_uninstall_legacy_calls_uninstall_legacy_vllm(self):
        with (
            _patch_remote(False),
            patch("aria.scripts.vllm.uninstall_vllm") as mock_uninstall,
            patch("aria.scripts.vllm.uninstall_legacy_vllm") as mock_legacy,
        ):
            result = runner.invoke(app, ["uninstall", "--legacy"])

        assert result.exit_code == 0
        mock_legacy.assert_called_once()
        mock_uninstall.assert_not_called()

    def test_uninstall_remote_refuses(self):
        with (
            _patch_remote(True),
            patch("aria.scripts.vllm.uninstall_vllm") as mock_uninstall,
        ):
            result = runner.invoke(app, ["uninstall"])

        assert result.exit_code == 0
        assert "externally managed" in result.output
        mock_uninstall.assert_not_called()


class TestStatus:
    """aria vllm status — shows venv row + legacy notice."""

    def test_status_shows_venv_row_when_installed(self):
        with (
            patch("aria.cli.vllm.is_vllm_installed", return_value=True),
            patch("aria.cli.vllm.get_vllm_version", return_value="0.24.0"),
            patch(
                "aria.config.api.Vllm.get_venv_path",
                return_value="/home/u/.aria/venvs/vllm",
            ),
            patch("aria.scripts.vllm.detect_legacy_vllm", return_value=None),
        ):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Installed" in result.output
        assert "0.24.0" in result.output
        assert "/home/u/.aria/venvs/vllm" in result.output

    def test_status_shows_install_hint_when_not_installed(self):
        with (
            patch("aria.cli.vllm.is_vllm_installed", return_value=False),
            patch("aria.scripts.vllm.detect_legacy_vllm", return_value=None),
        ):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Not installed" in result.output
        assert "aria vllm install" in result.output

    def test_status_shows_legacy_notice(self):
        with (
            patch("aria.cli.vllm.is_vllm_installed", return_value=False),
            patch("aria.scripts.vllm.detect_legacy_vllm", return_value="0.20.0"),
        ):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "ignored" in result.output
        assert "aria vllm uninstall --legacy" in result.output


class TestInstall:
    """aria vllm install — routes to isolated installer + legacy notice."""

    def test_install_passes_version_flag(self):
        with (
            patch("aria.scripts.vllm.install_vllm") as mock_install,
            patch("aria.scripts.vllm.detect_legacy_vllm", return_value=None),
        ):
            result = runner.invoke(app, ["install", "--version", "0.30.0"])

        assert result.exit_code == 0
        mock_install.assert_called_once_with(version="0.30.0")

    def test_install_shows_legacy_notice(self):
        with (
            patch("aria.scripts.vllm.install_vllm"),
            patch("aria.scripts.vllm.detect_legacy_vllm", return_value="0.20.0"),
        ):
            result = runner.invoke(app, ["install"])

        assert result.exit_code == 0
        assert "ignored" in result.output
