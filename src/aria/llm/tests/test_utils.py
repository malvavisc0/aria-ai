"""Tests for LLM instruction-context utilities."""

from types import SimpleNamespace

from aria.llm import _utils


def test_default_shell_uses_shell_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/fish")

    assert _utils._default_shell() == "fish"


def test_default_shell_uses_account_shell_when_environment_missing(monkeypatch) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    user = type("User", (), {"pw_shell": "/bin/zsh"})()
    monkeypatch.setattr("pwd.getpwuid", lambda _uid: user)

    assert _utils._default_shell() == "zsh"


def test_gpu_line_lists_detected_devices(monkeypatch) -> None:
    gpus = [
        SimpleNamespace(name="NVIDIA RTX 3090", total_memory=24576),
        SimpleNamespace(name="NVIDIA RTX 3090", total_memory=24576),
    ]
    monkeypatch.setattr("aria.helpers.nvidia.detect_gpus_with_details", lambda: gpus)

    assert _utils._gpu_line() == (
        "- **GPU**: NVIDIA RTX 3090 (24 GiB VRAM), NVIDIA RTX 3090 (24 GiB VRAM)"
    )


def test_gpu_line_omitted_when_no_gpu_detected(monkeypatch) -> None:
    monkeypatch.setattr("aria.helpers.nvidia.detect_gpus_with_details", lambda: [])

    assert _utils._gpu_line() is None
