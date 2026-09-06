"""Tests for the aria mcp CLI (TOML add/list/remove against config.toml)."""

from pathlib import Path

from typer.testing import CliRunner

from aria.cli import mcp
from aria.cli.mcp import _load_servers, _remove_server_block, app

runner = CliRunner()

_BASE_CONFIG = """\
[project]
user_env = []

[features.mcp]
enabled = true

[UI]
name = "Aria"
"""


def _write_config(tmp_path: Path, content: str = _BASE_CONFIG) -> Path:
    config = tmp_path / ".chainlit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(content)
    return config


def _use_config(monkeypatch, tmp_path: Path) -> Path:
    config = _write_config(tmp_path)
    monkeypatch.setattr(mcp.Data, "path", tmp_path)
    return config


def test_add_stdio_appends_server_block(monkeypatch, tmp_path) -> None:
    config = _use_config(monkeypatch, tmp_path)

    result = runner.invoke(
        app, ["add", "fs", "--command", "uvx mcp-server-fs ~", "--env", "TOKEN=abc"]
    )

    assert result.exit_code == 0, result.output
    servers = _load_servers(config)
    assert servers == [
        {
            "name": "fs",
            "type": "stdio",
            "command": "uvx mcp-server-fs ~",
            "env": {"TOKEN": "abc"},
        }
    ]


def test_add_url_defaults_to_streamable_http(monkeypatch, tmp_path) -> None:
    config = _use_config(monkeypatch, tmp_path)

    result = runner.invoke(
        app, ["add", "remote", "--url", "https://mcp.example.com/mcp"]
    )

    assert result.exit_code == 0, result.output
    servers = _load_servers(config)
    assert servers[0]["type"] == "streamable-http"
    assert servers[0]["url"] == "https://mcp.example.com/mcp"


def test_add_rejects_duplicate_name_case_insensitive(monkeypatch, tmp_path) -> None:
    _use_config(monkeypatch, tmp_path)
    runner.invoke(app, ["add", "fs", "--command", "uvx mcp-server-fs ~"])

    result = runner.invoke(app, ["add", "FS", "--command", "uvx other"])

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_add_requires_command_or_url(monkeypatch, tmp_path) -> None:
    _use_config(monkeypatch, tmp_path)

    result = runner.invoke(app, ["add", "fs"])

    assert result.exit_code != 0
    assert "--command" in result.output


def test_remove_deletes_only_the_named_block(monkeypatch, tmp_path) -> None:
    config = _use_config(monkeypatch, tmp_path)
    runner.invoke(app, ["add", "fs", "--command", "uvx mcp-server-fs ~"])
    runner.invoke(app, ["add", "remote", "--url", "https://mcp.example.com/mcp"])

    result = runner.invoke(app, ["remove", "fs"])

    assert result.exit_code == 0, result.output
    servers = _load_servers(config)
    assert [s["name"] for s in servers] == ["remote"]
    # The rest of the file (user edits, comments) is untouched.
    assert "[UI]" in config.read_text()


def test_remove_unknown_name_fails(monkeypatch, tmp_path) -> None:
    _use_config(monkeypatch, tmp_path)

    result = runner.invoke(app, ["remove", "nope"])

    assert result.exit_code == 1
    assert "No server named" in result.output


def test_remove_block_helper_preserves_surrounding_content() -> None:
    content = (
        "[features.mcp]\nenabled = true\n\n"
        "[[features.mcp.servers]]\n"
        'name = "a"\ntype = "stdio"\ncommand = "uvx a"\n\n'
        "[[features.mcp.servers]]\n"
        'name = "b"\ntype = "sse"\nurl = "https://x/sse"\n\n'
        '[UI]\nname = "Aria"\n'
    )

    updated = _remove_server_block(content, "a")

    assert updated is not None
    assert '"a"' not in updated
    assert '"b"' in updated
    assert updated.startswith("[features.mcp]")
    assert updated.endswith('[UI]\nname = "Aria"\n')


def test_remove_block_ignores_name_like_keys_and_comments() -> None:
    content = (
        "[[features.mcp.servers]]\n"
        "# name = commented-out\n"
        'nameserver = "not-a-name"\n'
        'name = "real"\n'
        'type = "stdio"\n'
        'command = "uvx real"\n'
    )

    assert _remove_server_block(content, "commented-out") is None
    assert _remove_server_block(content, "not-a-name") is None
    assert _remove_server_block(content, "real") == ""


def test_add_fails_loudly_on_broken_toml(monkeypatch, tmp_path) -> None:
    config = _write_config(tmp_path, "[features.mcp\nnot toml")
    monkeypatch.setattr(mcp.Data, "path", tmp_path)

    result = runner.invoke(app, ["add", "fs", "--command", "uvx mcp-server-fs ~"])

    assert result.exit_code == 1
    assert "not valid TOML" in result.output
    assert "uvx" not in config.read_text()


def test_list_renders_table(monkeypatch, tmp_path) -> None:
    _use_config(monkeypatch, tmp_path)
    runner.invoke(app, ["add", "fs", "--command", "uvx mcp-server-fs ~"])

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "fs" in result.output
    assert "stdio" in result.output


def test_list_empty_shows_hint(monkeypatch, tmp_path) -> None:
    _use_config(monkeypatch, tmp_path)

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "No MCP servers configured" in result.output
