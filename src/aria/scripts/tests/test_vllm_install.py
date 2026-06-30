"""Tests for vLLM install/detect utilities in scripts/vllm.py.

Covers the detached install model: vLLM lives in an isolated venv at
``Vllm.get_venv_path()`` and is detected via a filesystem ``dist-info``
glob (never an ``import vllm`` subprocess).
"""

import importlib.metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from aria.scripts.vllm import (
    _make_shim,
    _resolve_extra_index_url,
    detect_install_target,
    detect_legacy_vllm,
    get_latest_vllm_version,
    get_vllm_version,
    install_vllm,
    is_vllm_installed,
    uninstall_legacy_vllm,
    uninstall_vllm,
    update_vllm,
)


class TestDetectInstallTarget:
    """Tests for detect_install_target()."""

    def test_returns_cu126_for_cuda_126(self):
        """CUDA 12.6+ should map to cu126."""
        with patch("aria.helpers.nvidia.get_cuda_version", return_value="12.6"):
            result = detect_install_target()
        assert result == "cu126"

    def test_returns_cu124_for_cuda_124(self):
        """CUDA 12.4 should map to cu124."""
        with patch("aria.helpers.nvidia.get_cuda_version", return_value="12.4"):
            result = detect_install_target()
        assert result == "cu124"

    def test_returns_cu121_for_cuda_121(self):
        """CUDA 12.1 should map to cu121."""
        with patch("aria.helpers.nvidia.get_cuda_version", return_value="12.1"):
            result = detect_install_target()
        assert result == "cu121"

    def test_returns_rocm6_when_rocm_smi_present(self):
        """rocm-smi on PATH should map to rocm6."""
        with (
            patch(
                "aria.helpers.nvidia.get_cuda_version",
                return_value=None,
            ),
            patch("shutil.which", return_value="/usr/bin/rocm-smi"),
        ):
            result = detect_install_target()
        assert result == "rocm6"

    def test_returns_cpu_when_no_gpu(self):
        """No GPU detection → cpu fallback."""
        with (
            patch(
                "aria.helpers.nvidia.get_cuda_version",
                return_value=None,
            ),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.is_dir", return_value=False),
        ):
            result = detect_install_target()
        assert result == "cpu"

    def test_returns_string(self):
        """Result must always be a known target string."""
        result = detect_install_target()
        assert isinstance(result, str)
        assert result in ("cu126", "cu124", "cu121", "cu118", "rocm6", "cpu")


class TestIsVllmInstalled:
    """Tests for the filesystem-based is_vllm_installed()."""

    def test_returns_true_when_venv_and_dist_info_present(self, tmp_path):
        """Installed = venv python exists + vllm dist-info present."""
        venv = tmp_path / "vllm"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("")
        sp = venv / "lib" / "python3.12" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "vllm-0.24.0.dist-info").mkdir()

        with (
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=venv / "bin" / "python",
            ),
            patch("aria.config.api.Vllm.get_site_packages", return_value=sp),
        ):
            assert is_vllm_installed() is True

    def test_returns_false_when_dist_info_missing(self, tmp_path):
        """No dist-info → not installed, even if the interpreter exists."""
        venv = tmp_path / "vllm"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("")
        sp = venv / "lib" / "python3.12" / "site-packages"
        sp.mkdir(parents=True)

        with (
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=venv / "bin" / "python",
            ),
            patch("aria.config.api.Vllm.get_site_packages", return_value=sp),
        ):
            assert is_vllm_installed() is False

    def test_returns_false_when_no_venv(self):
        """No interpreter and no site-packages → not installed."""
        with (
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=Path("/nonexistent/python"),
            ),
            patch("aria.config.api.Vllm.get_site_packages", return_value=None),
        ):
            assert is_vllm_installed() is False

    def test_does_not_spawn_subprocess_or_import_torch(self, tmp_path):
        """is_vllm_installed() must be a pure filesystem check."""
        venv = tmp_path / "vllm"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("")
        sp = venv / "lib" / "python3.12" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "vllm-0.24.0.dist-info").mkdir()

        with (
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=venv / "bin" / "python",
            ),
            patch("aria.config.api.Vllm.get_site_packages", return_value=sp),
            patch("aria.scripts.vllm.subprocess") as mock_subprocess,
        ):
            result = is_vllm_installed()

        assert result is True
        assert not mock_subprocess.run.called


class TestGetVllmVersion:
    """Tests for get_vllm_version() (reads dist-info dir name)."""

    def test_returns_version_from_dist_info_name(self, tmp_path):
        sp = tmp_path / "sp"
        sp.mkdir()
        (sp / "vllm-0.24.0.dist-info").mkdir()

        with patch("aria.config.api.Vllm.get_site_packages", return_value=sp):
            assert get_vllm_version() == "0.24.0"

    def test_returns_empty_when_not_installed(self):
        with patch("aria.config.api.Vllm.get_site_packages", return_value=None):
            assert get_vllm_version() == ""


class TestResolveExtraIndexUrl:
    """Tests for _resolve_extra_index_url()."""

    def test_cu124_returns_cu124_url(self):
        assert _resolve_extra_index_url("cu124") == (
            "https://download.pytorch.org/whl/cu124"
        )

    def test_cpu_returns_none(self):
        assert _resolve_extra_index_url("cpu") is None

    def test_cu126_cuda13_returns_none(self):
        """CUDA 13+ with cu126 target uses default PyPI wheels."""
        with patch("aria.helpers.nvidia.get_cuda_version", return_value="13.0"):
            assert _resolve_extra_index_url("cu126") is None

    def test_cu126_cuda12_returns_cu126_url(self):
        with patch("aria.helpers.nvidia.get_cuda_version", return_value="12.6"):
            assert _resolve_extra_index_url("cu126") == (
                "https://download.pytorch.org/whl/cu126"
            )


class TestMakeShim:
    """Tests for _make_shim() (symlink with shell-wrapper fallback)."""

    def test_creates_symlink(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        target = venv / "bin" / "vllm"
        target.write_text("#!/bin/sh\n")

        with patch("aria.scripts.vllm.Bin.path", tmp_path / "bin"):
            shim = _make_shim(venv)

        assert shim.is_symlink()
        assert shim.resolve() == target.resolve()

    def test_falls_back_to_shell_wrapper_on_oserror(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        target = venv / "bin" / "vllm"
        target.write_text("#!/bin/sh\n")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        with (
            patch("aria.scripts.vllm.Bin.path", bin_dir),
            patch("pathlib.Path.symlink_to", side_effect=OSError("nope")),
        ):
            shim = _make_shim(venv)

        assert shim.exists()
        assert not shim.is_symlink()
        text = shim.read_text()
        assert text.startswith("#!/bin/sh")
        assert str(target) in text


class TestInstallVllm:
    """Tests for install_vllm() platform + flow guards."""

    def test_raises_on_macos(self):
        """Should raise RuntimeError with clear message on macOS."""
        with patch("aria.scripts.vllm.sys") as mock_sys:
            mock_sys.platform = "darwin"
            with pytest.raises(RuntimeError, match="not supported on macOS"):
                install_vllm()

    def test_does_not_raise_on_linux(self, tmp_path):
        """Linux install flow builds the venv, installs, and makes the shim."""
        venv = tmp_path / "venvs" / "vllm"
        venv.parent.mkdir(parents=True)

        with (
            patch("aria.scripts.vllm.sys") as mock_sys,
            patch("aria.scripts.vllm.detect_install_target", return_value="cpu"),
            patch("aria.scripts.vllm._resolve_extra_index_url", return_value=None),
            patch("aria.config.api.Vllm.get_venv_path", return_value=venv),
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=venv / "bin" / "python",
            ),
            patch("aria.config.api.Vllm.version", "0.24.0", create=True),
            patch("aria.scripts.vllm._create_venv") as mock_create,
            patch("aria.scripts.vllm._make_shim") as mock_shim,
            patch("aria.scripts.vllm.subprocess.run") as mock_run,
            patch("aria.scripts.vllm.shutil.which", return_value=None),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.24.0"),
        ):
            mock_sys.platform = "linux"
            install_vllm()

        mock_create.assert_called_once_with(venv)
        mock_shim.assert_called_once_with(venv)
        # subprocess.run used for both the install and the `vllm --version`
        # verification, so it must be called at least twice.
        assert mock_run.call_count >= 2

    def test_uses_pinned_version(self, tmp_path):
        """install_vllm(version=...) must install vllm==<version>."""
        venv = tmp_path / "venv"
        venv.mkdir()
        cmds: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            cmds.append(cmd)

        with (
            patch("aria.scripts.vllm.sys") as mock_sys,
            patch("aria.scripts.vllm.detect_install_target", return_value="cpu"),
            patch("aria.scripts.vllm._resolve_extra_index_url", return_value=None),
            patch("aria.config.api.Vllm.get_venv_path", return_value=venv),
            patch(
                "aria.config.api.Vllm.get_python_executable",
                return_value=venv / "bin" / "python",
            ),
            patch("aria.scripts.vllm._create_venv"),
            patch("aria.scripts.vllm._make_shim"),
            patch("aria.scripts.vllm.subprocess.run", side_effect=fake_run),
            patch("aria.scripts.vllm.shutil.which", return_value=None),
            patch("aria.scripts.vllm.get_vllm_version", return_value="0.99.0"),
        ):
            mock_sys.platform = "linux"
            install_vllm(version="0.99.0")

        # The install call must reference vllm==0.99.0 (a later verify
        # call invokes `vllm --version` without the spec).
        assert any("vllm==0.99.0" in cmd for cmd in cmds)


class TestUninstallVllm:
    """Tests for uninstall_vllm()."""

    def test_removes_venv_and_shim(self, tmp_path):
        venv = tmp_path / "venvs" / "vllm"
        venv.mkdir(parents=True)
        (venv / "marker").write_text("")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "vllm"
        shim.write_text("shim")

        with (
            patch("aria.config.api.Vllm.get_venv_path", return_value=venv),
            patch("aria.scripts.vllm.Bin.path", bin_dir),
        ):
            uninstall_vllm()

        assert not venv.exists()
        assert not shim.exists()

    def test_noop_when_absent(self, tmp_path):
        with (
            patch(
                "aria.config.api.Vllm.get_venv_path", return_value=tmp_path / "missing"
            ),
            patch("aria.scripts.vllm.Bin.path", tmp_path / "bin"),
        ):
            uninstall_vllm()  # should not raise


class TestGetLatestVllmVersion:
    """Tests for get_latest_vllm_version()."""

    def test_returns_version_on_success(self):
        payload = b'{"info": {"version": "0.25.0"}}'

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch("aria.scripts.vllm.urlopen", return_value=_Resp()):
            assert get_latest_vllm_version() == "0.25.0"

    def test_returns_none_on_failure(self):
        with patch("aria.scripts.vllm.urlopen", side_effect=OSError("offline")):
            assert get_latest_vllm_version() is None


class TestUpdateVllm:
    """Tests for update_vllm()."""

    def test_explicit_version_recreates_venv(self, tmp_path):
        """update_vllm(version=...) uninstalls then installs at that version."""
        with (
            patch("aria.scripts.vllm.uninstall_vllm") as mock_uninstall,
            patch("aria.scripts.vllm.install_vllm") as mock_install,
        ):
            update_vllm(version="0.30.0")

        mock_uninstall.assert_called_once()
        mock_install.assert_called_once_with(version="0.30.0")

    def test_falls_back_to_pin_when_offline(self):
        """No explicit version + PyPI lookup fails → use Vllm.version."""
        with (
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value=None),
            patch("aria.config.api.Vllm.version", "0.24.0", create=True),
            patch("aria.scripts.vllm.uninstall_vllm"),
            patch("aria.scripts.vllm.install_vllm") as mock_install,
        ):
            update_vllm()

        mock_install.assert_called_once_with(version="0.24.0")

    def test_uses_latest_from_pypi(self):
        with (
            patch("aria.scripts.vllm.get_latest_vllm_version", return_value="9.9.9"),
            patch("aria.scripts.vllm.uninstall_vllm"),
            patch("aria.scripts.vllm.install_vllm") as mock_install,
        ):
            update_vllm()

        mock_install.assert_called_once_with(version="9.9.9")


class TestLegacy:
    """Tests for legacy in-Aria-env detection & cleanup."""

    def test_detect_legacy_returns_version(self):
        with patch.object(importlib.metadata, "version", return_value="0.20.0"):
            assert detect_legacy_vllm() == "0.20.0"

    def test_detect_legacy_returns_none_when_absent(self):
        with patch.object(
            importlib.metadata,
            "version",
            side_effect=importlib.metadata.PackageNotFoundError("vllm"),
        ):
            assert detect_legacy_vllm() is None

    def test_uninstall_legacy_uses_uv_when_available(self):
        with (
            patch("aria.scripts.vllm.shutil.which", return_value="/usr/bin/uv"),
            patch("aria.scripts.vllm.subprocess.run") as mock_run,
        ):
            uninstall_legacy_vllm()

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:3] == ["uv", "pip", "uninstall"]

    def test_uninstall_legacy_falls_back_to_pip(self):
        with (
            patch("aria.scripts.vllm.shutil.which", return_value=None),
            patch("aria.scripts.vllm.subprocess.run") as mock_run,
            patch("aria.scripts.vllm.sys.executable", "/usr/bin/python3"),
        ):
            uninstall_legacy_vllm()

        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["/usr/bin/python3", "-m"]
        assert "pip" in cmd and "uninstall" in cmd


class TestExternallyManagedVenvGuard:
    """Aria must never create/destroy a user-provided ARIA_VLLM_VENV."""

    def test_install_refuses_when_externally_managed(self, tmp_path):
        with (
            patch("aria.scripts.vllm.sys") as mock_sys,
            patch("aria.config.api.Vllm.is_externally_managed_venv", return_value=True),
            patch("aria.config.api.Vllm.get_venv_path", return_value=tmp_path / "ext"),
            patch("aria.scripts.vllm._create_venv") as mock_create,
            patch("aria.scripts.vllm.subprocess.run") as mock_run,
        ):
            mock_sys.platform = "linux"
            with pytest.raises(RuntimeError, match="externally managed"):
                install_vllm()
        mock_create.assert_not_called()
        mock_run.assert_not_called()

    def test_uninstall_refuses_when_externally_managed(self, tmp_path):
        ext = tmp_path / "ext"
        ext.mkdir()
        (ext / "marker").write_text("")
        with (
            patch("aria.config.api.Vllm.is_externally_managed_venv", return_value=True),
            patch("aria.config.api.Vllm.get_venv_path", return_value=ext),
        ):
            with pytest.raises(RuntimeError, match="externally managed"):
                uninstall_vllm()
        # The user's venv must remain untouched.
        assert ext.exists()
        assert (ext / "marker").exists()


class TestCreateVenv:
    """Tests for _create_venv() interpreter pinning."""

    def test_uv_venv_pins_sys_executable(self, tmp_path):
        from aria.scripts.vllm import _create_venv

        venv = tmp_path / "venvs" / "vllm"
        with (
            patch("aria.scripts.vllm.shutil.which", return_value="/usr/bin/uv"),
            patch("aria.scripts.vllm.sys.executable", "/aria/.venv/bin/python"),
            patch("aria.scripts.vllm.subprocess.run") as mock_run,
        ):
            _create_venv(venv)

        cmd = mock_run.call_args[0][0]
        assert cmd[:4] == ["uv", "venv", "--python", "/aria/.venv/bin/python"]
