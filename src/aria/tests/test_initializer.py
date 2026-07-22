"""Tests for first-run initialization, focusing on CHAINLIT_AUTH_SECRET
persistence across container restarts (the Docker mounted-.env scenario).
"""

import os
from importlib.resources import as_file, files
from pathlib import Path

import pytest

from aria.initializer import (
    _has_valid_secret,
    generate_secret,
    is_initialized,
    setup_env_file,
)


def test_root_env_example_matches_packaged_template() -> None:
    """The repo-root .env.example must stay byte-identical to the packaged
    src/aria/.env.example that the initializer copies at runtime.  Drift
    between the two would give Docker users a different default config than
    pip/non-Docker users.
    """
    root_example = Path(".env.example")
    if not root_example.exists():
        pytest.skip("repo-root .env.example not present (e.g. installed wheel)")
    with as_file(files("aria").joinpath(".env.example")) as packaged:
        assert root_example.read_text() == packaged.read_text(), (
            "Root .env.example has drifted from src/aria/.env.example — "
            "update both to keep Docker and non-Docker defaults in sync."
        )


def test_has_valid_secret_rejects_placeholders() -> None:
    assert not _has_valid_secret("")
    assert not _has_valid_secret("your-secret-here")
    assert not _has_valid_secret("changeme")
    assert _has_valid_secret("a-real-secret-value")


def test_is_initialized_false_when_no_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
    assert not is_initialized()


def test_is_initialized_true_when_secret_in_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "env-secret-123")
    assert is_initialized()


def test_is_initialized_loads_secret_from_file_into_env(
    monkeypatch, tmp_path: Path
) -> None:
    """When the secret lives only in the ARIA_HOME .env (a persisted Docker
    restart), is_initialized() must populate os.environ so Chainlit sees it."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)

    secret = generate_secret()
    (tmp_path / ".env").write_text(f"CHAINLIT_AUTH_SECRET = {secret}\n")

    assert is_initialized()
    assert os.environ["CHAINLIT_AUTH_SECRET"] == secret


def test_setup_env_file_persists_secret_in_docker_path(
    monkeypatch, tmp_path: Path
) -> None:
    """Docker path: mounted .env has CHAT_MODEL but no secret. setup_env_file()
    must generate AND persist the secret to the ARIA_HOME .env file."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
    monkeypatch.setenv("CHAT_MODEL", "test-model")

    env_file = tmp_path / ".env"
    assert not env_file.exists()

    assert setup_env_file() is True

    # Secret was set in the environment
    secret = os.environ.get("CHAINLIT_AUTH_SECRET", "")
    assert _has_valid_secret(secret)

    # Secret was persisted to the ARIA_HOME .env file
    assert env_file.exists()
    content = env_file.read_text()
    assert "CHAINLIT_AUTH_SECRET" in content
    assert secret in content


def test_secret_survives_restart(monkeypatch, tmp_path: Path) -> None:
    """Simulate a container restart: first boot persists the secret, second
    boot (env cleared) reloads it via is_initialized()."""
    monkeypatch.setenv("ARIA_HOME", str(tmp_path))
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
    monkeypatch.setenv("CHAT_MODEL", "test-model")

    # Boot 1: generate + persist
    setup_env_file()
    persisted_secret = os.environ["CHAINLIT_AUTH_SECRET"]

    # Boot 2: env cleared (fresh process), secret only in the persisted file
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
    assert is_initialized()
    assert os.environ["CHAINLIT_AUTH_SECRET"] == persisted_secret
