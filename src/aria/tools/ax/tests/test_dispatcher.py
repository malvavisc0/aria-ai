"""Tests for the ax dispatcher tool."""

import json
from unittest.mock import patch

import pytest

from aria.tools.ax.dispatcher import _DISPATCH, _build_help, ax


class TestHelp:
    """Test the help subcommand."""

    def test_help_all_families(self):
        result = _build_help(None)
        data = json.loads(result)
        assert "families" in data["data"]
        assert "web" in data["data"]["families"]
        assert "knowledge" in data["data"]["families"]

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


class TestDispatchTable:
    """Test the dispatch table structure."""

    def test_all_families_exist(self):
        expected = {
            "web",
            "knowledge",
            "finance",
            "imdb",
            "http",
            "dev",
            "processes",
            "documents",
            "check",
            "worker",
        }
        assert set(_DISPATCH.keys()) == expected

    def test_web_commands(self):
        assert set(_DISPATCH["web"].keys()) == {
            "search",
            "fetch",
            "visit",
            "click",
            "close",
            "weather",
            "youtube",
        }

    def test_knowledge_commands(self):
        assert set(_DISPATCH["knowledge"].keys()) == {
            "store",
            "recall",
            "search",
            "list",
            "update",
            "delete",
        }

    def test_finance_commands(self):
        assert set(_DISPATCH["finance"].keys()) == {"stock", "company", "news"}

    def test_imdb_commands(self):
        assert set(_DISPATCH["imdb"].keys()) == {
            "search",
            "movie",
            "person",
            "filmography",
            "episodes",
            "reviews",
            "trivia",
        }

    def test_processes_commands(self):
        assert set(_DISPATCH["processes"].keys()) == {
            "start",
            "stop",
            "status",
            "logs",
            "list",
            "restart",
            "signal",
        }

    def test_check_commands(self):
        assert set(_DISPATCH["check"].keys()) == {"extras"}


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
    async def test_dispatches_knowledge_with_action(self):
        mock_response = '{"tool":"knowledge","data":{"entries":[]}}'
        with patch(
            "aria.tools.knowledge.functions.knowledge",
            return_value=mock_response,
        ) as mock_fn:
            result = await ax(
                reason="store pref",
                family="knowledge",
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
