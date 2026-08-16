"""Tests for the ax dispatcher tool."""

import json
import re
from unittest.mock import patch

import pytest

from aria.tools.ax.dispatcher import _DISPATCH, _build_help, _help_lookup, ax
from aria.tools.execution_context import (
    ExecutionContext,
    reset_execution_context,
    set_execution_context,
)


def _parse_commands(section: str) -> set[str]:
    """Parse the command column (first backtick-wrapped cell) of a section."""
    cmds: set[str] = set()
    for line in section.splitlines():
        m = re.match(r"\|\s*`([a-z_]+)`\s*\|", line)
        if m:
            cmds.add(m.group(1))
    return cmds


def _parse_required_args(section: str) -> dict[str, set[str]]:
    """Parse each command row's Required column args.

    Returns ``{command: {arg, ...}}``. ``-`` / empty cells yield an empty set.
    Only backtick-wrapped tokens count as arg names (e.g. `` `code` (or
    `file`) `` → ``{"code", "file"}``).
    """
    out: dict[str, set[str]] = {}
    for line in section.splitlines():
        m = re.match(r"\|\s*`([a-z_]+)`\s*\|\s*([^|]*)\|", line)
        if not m:
            continue
        cmd, req = m.group(1), m.group(2)
        args = set(re.findall(r"`([a-z_]+)`", req))
        args.discard("—")
        out[cmd] = args
    return out


class TestHelp:
    """Test the help subcommand."""

    def test_help_all_families(self):
        result = _build_help(None)
        data = json.loads(result)
        assert "families" in data["data"]
        assert "web" in data["data"]["families"]
        assert "memory" in data["data"]["families"]

    def test_help_single_family(self):
        result = _build_help("web")
        data = json.loads(result)
        assert data["data"]["family"] == "web"
        assert "search" in data["data"]["commands"]
        assert "fetch" in data["data"]["commands"]

    def test_help_unknown_family(self):
        result = _build_help("nonexistent")
        data = json.loads(result)
        # Falls through to all-families help
        assert "families" in data["data"]


class TestHelpLookup:
    """Test the on-demand help lookup command."""

    def test_known_topic_returns_section(self):
        result = _help_lookup("worker")
        data = json.loads(result)
        assert data["data"]["topic"] == "worker"
        section = data["data"]["section"]
        assert section.startswith("## worker")
        assert "spawn" in section
        assert "prompt" in section

    @pytest.mark.asyncio
    async def test_lookup_via_ax(self):
        result = await ax(
            reason="need worker spawn args",
            family="help",
            command="lookup",
            args={"topic": "worker"},
        )
        data = json.loads(result)
        assert data["data"]["topic"] == "worker"
        assert data["data"]["section"].startswith("## worker")

    def test_unknown_topic_returns_did_you_mean(self):
        result = _help_lookup("notarealfamily")
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "unknown_topic"
        available = data["data"]["error"]["available_topics"]
        assert "worker" in available
        assert set(available) == set(_DISPATCH.keys())

    @pytest.mark.asyncio
    async def test_unknown_topic_via_ax(self):
        result = await ax(
            reason="test",
            family="help",
            command="lookup",
            args={"topic": "notarealfamily"},
        )
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "unknown_topic"

    def test_empty_topic_returns_index(self):
        result = _help_lookup("")
        data = json.loads(result)
        assert "topics" in data["data"]
        assert set(data["data"]["topics"]) == set(_DISPATCH.keys())

    @pytest.mark.asyncio
    async def test_empty_topic_via_ax(self):
        result = await ax(
            reason="list topics",
            family="help",
            command="lookup",
            args={},
        )
        data = json.loads(result)
        assert "topics" in data["data"]

    @pytest.mark.asyncio
    async def test_help_family_without_command_falls_back_to_index(self):
        """Backward compat: family='help' with no command returns all-families."""
        result = await ax(reason="test", family="help", command="anything")
        data = json.loads(result)
        assert "families" in data["data"]

    @pytest.mark.asyncio
    async def test_help_command_within_family_still_lists_commands(self):
        """Regression guard: command='help' in a family returns command names."""
        result = await ax(reason="test", family="finance", command="help")
        data = json.loads(result)
        assert data["data"]["family"] == "finance"
        assert "stock" in data["data"]["commands"]


class TestReferenceParity:
    """The ax command reference must stay in sync with the dispatch table."""

    @staticmethod
    def _reference_content() -> str:
        from aria.tools.ax.dispatcher import _ax_reference_path

        return _ax_reference_path().read_text(encoding="utf-8")

    def test_reference_families_match_dispatch(self):
        from aria.tools.ax.dispatcher import _reference_topics

        topics = set(_reference_topics(self._reference_content()))
        assert topics == set(_DISPATCH.keys())

    def test_reference_commands_match_dispatch_per_family(self):
        from aria.tools.ax.dispatcher import _extract_section

        content = self._reference_content()
        for family, cmds in _DISPATCH.items():
            section = _extract_section(content, family)
            assert section is not None, f"family {family!r} missing from reference"
            ref_cmds = _parse_commands(section)
            assert ref_cmds == set(cmds.keys()), (
                f"{family}: reference {sorted(ref_cmds)} "
                f"!= dispatch {sorted(cmds.keys())}"
            )

    def test_reference_required_args_survive_dispatch(self):
        """Each documented Required arg must be accepted by its target.

        Guards arg-name drift: if a target function's signature drops/renames
        a Required arg the reference still documents, ``_strip_unknown_kwargs``
        would silently drop it at call time — a behavior bug. Dry-running
        the stripper per documented arg catches this without false-positiving
        on action-dispatching families (process/worker/etc.) that share one
        union signature across commands.
        """
        from aria.tools.ax.dispatcher import (
            _DISPATCH,
            _extract_section,
            _load_target,
            _strip_unknown_kwargs,
        )

        content = self._reference_content()
        failures: list[str] = []
        for family, cmds in _DISPATCH.items():
            section = _extract_section(content, family)
            assert section is not None
            required = _parse_required_args(section)
            for cmd, (loader, _inject) in cmds.items():
                fn = _load_target(loader, "parity", family, cmd)
                if isinstance(fn, str):
                    failures.append(f"{family}.{cmd}: target load failed")
                    continue
                for arg in required.get(cmd, set()):
                    kept = _strip_unknown_kwargs(fn, {arg: None}, family, cmd)
                    if arg not in kept:
                        failures.append(
                            f"{family}.{cmd}: documented Required arg "
                            f"'{arg}' is dropped by the target signature"
                        )
        assert not failures, "\n".join(failures)


class TestDispatch:
    """Test actual dispatch routing."""

    @pytest.mark.asyncio
    async def test_unknown_family_returns_error(self):
        result = await ax(
            reason="test", family="nonexistent", command="search", args={}
        )
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "unknown_family"

    @pytest.mark.asyncio
    async def test_unknown_command_returns_error(self):
        result = await ax(reason="test", family="web", command="nonexistent", args={})
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "unknown_command"
        assert "search" in data["data"]["error"]["available_commands"]

    @pytest.mark.asyncio
    async def test_help_command(self):
        result = await ax(reason="test", family="finance", command="help")
        data = json.loads(result)
        assert data["data"]["family"] == "finance"
        assert "stock" in data["data"]["commands"]

    @pytest.mark.asyncio
    async def test_voice_family_in_help(self):
        result = _build_help("voice")
        data = json.loads(result)
        assert data["data"]["family"] == "voice"
        assert data["data"]["commands"] == ["transcribe"]

    @pytest.mark.asyncio
    async def test_dispatches_voice_transcribe(self):
        mock_response = '{"tool":"voice","data":{"text":"ok","chars":2}}'
        with patch(
            "aria.tools.voice.functions.transcribe",
            return_value=mock_response,
        ) as mock_fn:
            result = await ax(
                reason="transcribe audio",
                family="voice",
                command="transcribe",
                args={"file": "/tmp/a.wav"},
            )
            mock_fn.assert_called_once_with(
                reason="transcribe audio", file="/tmp/a.wav"
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_dispatches_to_web_search(self):
        mock_response = '{"tool":"web_search","data":{"results":[]}}'
        with patch(
            "aria.tools.search.webserp.web_search",
            return_value=mock_response,
        ) as mock_fn:
            result = await ax(
                reason="test search",
                family="web",
                command="search",
                args={"query": "python tutorials"},
            )
            mock_fn.assert_called_once_with(
                reason="test search", query="python tutorials"
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_dispatches_memory_with_action(self):
        mock_response = '{"tool":"memory","data":{"entries":[]}}'
        with patch(
            "aria.tools.memory.functions.memory",
            return_value=mock_response,
        ) as mock_fn:
            result = await ax(
                reason="store pref",
                family="memory",
                command="store",
                args={"key": "lang", "value": "Python"},
            )
            mock_fn.assert_called_once_with(
                reason="store pref", action="store", key="lang", value="Python"
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_dispatches_process_with_action(self):
        mock_response = '{"tool":"process","data":{"processes":[]}}'
        with patch(
            "aria.tools.process.functions.process", return_value=mock_response
        ) as mock_fn:
            result = await ax(
                reason="list procs",
                family="processes",
                command="list",
                args={},
            )
            mock_fn.assert_called_once_with(reason="list procs", action="list")
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_type_error_returns_helpful_message(self):
        with patch(
            "aria.tools.search.webserp.web_search",
            side_effect=TypeError("missing required argument: 'query'"),
        ):
            result = await ax(reason="test", family="web", command="search", args={})
            data = json.loads(result)
            assert data["data"]["error"]["code"] == "invalid_args"
            assert "query" in data["data"]["error"]["message"]

    @pytest.mark.asyncio
    async def test_empty_reason_returns_error(self):
        result = await ax(reason="", family="web", command="search")
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "missing_reason"
        assert "reason" in data["data"]["error"]["hint"].lower()

    @pytest.mark.asyncio
    async def test_no_args_returns_missing_reason(self):
        result = await ax()
        data = json.loads(result)
        # reason check fires before family/command check
        assert data["data"]["error"]["code"] == "missing_reason"

    @pytest.mark.asyncio
    async def test_empty_family_returns_error(self):
        result = await ax(reason="test", family="", command="search")
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "missing_required_args"

    @pytest.mark.asyncio
    async def test_empty_command_returns_error(self):
        result = await ax(reason="test", family="web", command="")
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "missing_required_args"

    @pytest.mark.asyncio
    async def test_worker_agent_cannot_spawn_nested_worker(self):
        token = set_execution_context(
            ExecutionContext(role="worker", worker_id="worker_x")
        )
        try:
            result = await ax(
                reason="delegate nested task",
                family="worker",
                command="spawn",
                args={"prompt": "nested"},
            )
        finally:
            reset_execution_context(token)
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "nested_worker_forbidden"

    @pytest.mark.asyncio
    async def test_worker_agent_cannot_use_memory(self):
        token = set_execution_context(
            ExecutionContext(role="worker", worker_id="worker_x")
        )
        try:
            result = await ax(
                reason="remember nested task",
                family="memory",
                command="store",
                args={"key": "x", "value": "y"},
            )
        finally:
            reset_execution_context(token)
        data = json.loads(result)
        assert data["data"]["error"]["code"] == "worker_memory_forbidden"

    @pytest.mark.asyncio
    async def test_strips_unknown_kwargs(self):
        """Unknown kwargs are stripped before forwarding to the target function."""

        # Define a local function with a known signature so inspect.signature
        # can determine the accepted parameters (unlike MagicMock which has
        # an empty signature and causes the filter to be skipped).
        def fake_search(reason, query):
            return '{"tool":"web_search","data":{"results":[]}}'

        with patch(
            "aria.tools.search.webserp.web_search",
            new=fake_search,
        ):
            result = await ax(
                reason="test search",
                family="web",
                command="search",
                args={"query": "python", "timeout": 30, "mode": "markdown"},
            )
            # The function should succeed — unknown args stripped silently
            data = json.loads(result)
            assert "results" in data["data"]

    @pytest.mark.asyncio
    async def test_dispatches_worker_spawn_with_steps(self):
        mock_response = '{"tool":"worker","data":{"worker_id":"w"}}'

        def fake_worker(reason, action, prompt="", expected="", steps=None, **kwargs):
            assert action == "spawn"
            assert steps == ["a", "b"]
            return mock_response

        with patch("aria.tools.worker.functions.worker", new=fake_worker):
            result = await ax(
                reason="delegate",
                family="worker",
                command="spawn",
                args={
                    "prompt": "p",
                    "expected": "e",
                    "steps": ["a", "b"],
                },
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_worker_spawn_strips_truly_unknown_kwarg(self):
        seen: dict = {}

        def fake_worker(reason, action, prompt="", expected="", steps=None, **kwargs):
            seen.update({"steps": steps, **kwargs})
            assert "bogus" not in kwargs
            return '{"tool":"worker","data":{}}'

        with patch("aria.tools.worker.functions.worker", new=fake_worker):
            await ax(
                reason="delegate",
                family="worker",
                command="spawn",
                args={
                    "prompt": "p",
                    "expected": "e",
                    "steps": ["a"],
                    "bogus": 1,
                },
            )
        assert seen["steps"] == ["a"]
