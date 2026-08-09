"""Unified ax dispatcher — routes family/command to native Python functions.

Replaces shell-based `ax <family> <command>` calls with direct function
dispatch. Same structured JSON responses, zero subprocess overhead.
"""

import inspect
from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from aria.tools import Reason, tool_response
from aria.tools.ax.exceptions import AxDispatchError
from aria.tools.decorators import log_tool_call

# ---------------------------------------------------------------------------
# Explicit schema exposed to the LLM (mirrors ShellToolSchema pattern).
# ---------------------------------------------------------------------------


class AxSchema(BaseModel):
    """Schema exposed to the LLM for the ax dispatcher."""

    reason: str = Field(
        description="Required. Brief explanation of why you are calling this."
    )
    family: str = Field(
        description=(
            "Tool family name. Use 'help' to list all families. "
            "Families: web, knowledge, finance, imdb, http, dev, processes, "
            "documents, check, worker."
        )
    )
    command: str = Field(
        description=(
            "Subcommand within the family. "
            "Use command='help' within a family to list its commands."
        )
    )
    args: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Arguments for the target function as a JSON dict "
            '(excluding \'reason\'). E.g. {"query": "python tutorials"}.'
        ),
    )


# ---------------------------------------------------------------------------
# Lazy import helpers (avoids importing all tool modules at load time)
# ---------------------------------------------------------------------------


def _web_search():
    from aria.tools.search.webserp import web_search

    return web_search


def _download():
    from aria.tools.search.download import download

    return download


def _visit_url():
    from aria.tools.browser.functions import visit_url

    return visit_url


def _browser_click():
    from aria.tools.browser.functions import browser_click

    return browser_click


def _weather():
    from aria.tools.search.weather import get_current_weather

    return get_current_weather


def _youtube():
    from aria.tools.search.youtube import get_youtube_video_transcription

    return get_youtube_video_transcription


def _browser_close():
    from aria.tools.browser.functions import browser_close

    return browser_close


def _knowledge():
    from aria.tools.knowledge.functions import knowledge

    return knowledge


def _finance_stock():
    from aria.tools.search.finance import fetch_current_stock_price

    return fetch_current_stock_price


def _finance_company():
    from aria.tools.search.finance import fetch_company_information

    return fetch_company_information


def _finance_news():
    from aria.tools.search.finance import fetch_ticker_news

    return fetch_ticker_news


def _imdb_search():
    from aria.tools.imdb.functions import search_imdb_titles

    return search_imdb_titles


def _imdb_movie():
    from aria.tools.imdb.functions import get_movie_details

    return get_movie_details


def _imdb_person():
    from aria.tools.imdb.functions import get_person_details

    return get_person_details


def _imdb_filmography():
    from aria.tools.imdb.functions import get_person_filmography

    return get_person_filmography


def _imdb_episodes():
    from aria.tools.imdb.functions import get_all_series_episodes

    return get_all_series_episodes


def _imdb_reviews():
    from aria.tools.imdb.functions import get_movie_reviews

    return get_movie_reviews


def _imdb_trivia():
    from aria.tools.imdb.functions import get_movie_trivia

    return get_movie_trivia


def _http_request():
    from aria.tools.http.functions import http_request

    return http_request


def _python():
    from aria.tools.development.python import python

    return python


def _process():
    from aria.tools.process.functions import process

    return process


def _extras():
    from aria.cli.extras import get_venv_extras_json

    return get_venv_extras_json


def _worker():
    from aria.tools.worker.functions import worker

    return worker


def _documents_convert():
    from aria.tools.documents.functions import convert

    return convert


def _documents_status():
    from aria.tools.documents.functions import status

    return status


# ---------------------------------------------------------------------------
# Dispatch table: family → command → (loader, inject_action?)
# inject_action means the command name is passed as action= parameter
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, dict[str, tuple[Callable, bool]]] = {
    "web": {
        "search": (_web_search, False),
        "fetch": (_download, False),
        "visit": (_visit_url, False),
        "click": (_browser_click, False),
        "close": (_browser_close, False),
        "weather": (_weather, False),
        "youtube": (_youtube, False),
    },
    "knowledge": {
        "store": (_knowledge, True),
        "recall": (_knowledge, True),
        "search": (_knowledge, True),
        "list": (_knowledge, True),
        "update": (_knowledge, True),
        "delete": (_knowledge, True),
    },
    "finance": {
        "stock": (_finance_stock, False),
        "company": (_finance_company, False),
        "news": (_finance_news, False),
    },
    "imdb": {
        "search": (_imdb_search, False),
        "movie": (_imdb_movie, False),
        "person": (_imdb_person, False),
        "filmography": (_imdb_filmography, False),
        "episodes": (_imdb_episodes, False),
        "reviews": (_imdb_reviews, False),
        "trivia": (_imdb_trivia, False),
    },
    "http": {
        "request": (_http_request, False),
    },
    "dev": {
        "run": (_python, False),
    },
    "processes": {
        "start": (_process, True),
        "stop": (_process, True),
        "status": (_process, True),
        "logs": (_process, True),
        "list": (_process, True),
        "restart": (_process, True),
        "signal": (_process, True),
    },
    "documents": {
        "convert": (_documents_convert, True),
        "status": (_documents_status, True),
    },
    "check": {
        "extras": (_extras, False),
    },
    "worker": {
        "spawn": (_worker, True),
        "list": (_worker, True),
        "status": (_worker, True),
        "logs": (_worker, True),
        "cancel": (_worker, True),
        "clean": (_worker, True),
    },
}


def _build_help(family: str | None) -> str:
    """Return help text for a family or all families."""
    if family and family in _DISPATCH:
        commands = list(_DISPATCH[family].keys())
        return tool_response(
            tool="ax",
            reason="help",
            data={"family": family, "commands": commands},
        )
    # All families
    data = {fam: list(cmds.keys()) for fam, cmds in _DISPATCH.items()}
    return tool_response(tool="ax", reason="help", data={"families": data})


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def _ax_error(reason: str, code: str, message: str, **extra: Any) -> str:
    """Build a structured ax error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if extra:
        err.update(extra)
    return tool_response(tool="ax", reason=reason, data={"error": err})


def _validate_ax_inputs(reason: str, family: str, command: str) -> str | None:
    """Validate required ax inputs; return an error response or None."""
    if not reason:
        return _ax_error(
            "missing_reason",
            "missing_reason",
            "The 'reason' argument is required. Explain why you are calling this tool.",
            hint="Pass a brief reason string, e.g. reason='Search for Python tutorials'.",
        )
    if not family or not command:
        return tool_response(
            tool="ax",
            reason=reason or "missing_args",
            data={
                "error": {
                    "code": "missing_required_args",
                    "message": "ax() requires 'family' and 'command' arguments.",
                    "expected": {
                        "reason": "Brief explanation of why you are calling this.",
                        "family": "Tool family: web, knowledge, finance, imdb, http, dev, processes, documents, check, worker",
                        "command": "Subcommand within the family",
                        "args": "Optional arguments dict (exclude 'reason')",
                    },
                }
            },
        )
    return None


def _resolve_entry(
    reason: str, family: str, command: str
) -> tuple[Callable, bool] | str:
    """Resolve a (loader, inject_action) entry, or return an error response."""
    family_commands = _DISPATCH.get(family)
    if family_commands is None:
        return _ax_error(
            reason,
            "unknown_family",
            f"Unknown family: '{family}'",
            available_families=list(_DISPATCH.keys()),
            hint="Use command='help' to see all families and commands.",
        )
    entry = family_commands.get(command)
    if entry is None:
        return _ax_error(
            reason,
            "unknown_command",
            f"Unknown command: '{command}' in family '{family}'",
            available_commands=list(family_commands.keys()),
            hint=f"Use ax(family='{family}', command='help') to see options.",
        )
    return entry


def _strip_unknown_kwargs(
    fn: Callable, kwargs: dict[str, Any], family: str, command: str
) -> dict[str, Any]:
    """Drop kwargs the target function does not accept (no **kwargs, real sig)."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return kwargs  # Built-in or C function — can't inspect, pass everything.
    accepted = set(sig.parameters.keys())
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not accepted or has_var_keyword:
        return kwargs
    dropped = set(kwargs.keys()) - accepted
    if dropped:
        logger.debug(
            "ax dispatch: stripping unknown args {} for {}.{}",
            dropped,
            family,
            command,
        )
    return {k: v for k, v in kwargs.items() if k in accepted}


def _load_target(
    loader: Callable, reason: str, family: str, command: str
) -> Callable | str:
    """Run the lazy import loader; return the function or an error response."""
    try:
        return loader()
    except ImportError as exc:
        logger.warning(f"ax dispatch: import failed for {family}.{command}: {exc}")
        return _ax_error(
            reason,
            "import_error",
            f"Could not load {family}.{command}: {exc}",
            recoverable=False,
        )


async def _invoke_target(
    fn: Callable,
    kwargs: dict[str, Any],
    reason: str,
    family: str,
    command: str,
) -> str:
    """Call the resolved target, mapping exceptions to ax error responses."""
    try:
        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)
    except TypeError as exc:
        logger.warning(f"ax dispatch: TypeError calling {family}.{command}: {exc}")
        return _ax_error(
            reason,
            "invalid_args",
            str(exc),
            hint="Check the required arguments for this command.",
            recoverable=True,
        )
    except AxDispatchError as exc:
        return _ax_error(reason, "dispatch_error", str(exc), recoverable=False)
    except Exception as exc:
        logger.error(
            f"ax dispatch: {family}.{command} raised {type(exc).__name__}: {exc}"
        )
        return _ax_error(
            reason,
            "execution_error",
            f"{type(exc).__name__}: {exc}",
            recoverable=True,
        )


@log_tool_call
async def ax(
    reason: Reason = "",
    family: str = "",
    command: str = "",
    args: dict[str, Any] | None = None,
) -> str:
    """Dispatch to a domain tool family with structured I/O.

    Use this for web, knowledge, finance, IMDb, HTTP, Python sandbox,
    and background-process actions. Use ``command="help"`` to list
    families or subcommands.

    Args:
        reason: Required. Brief explanation of why you are calling this.
        family: Tool family name.
        command: Subcommand within the family.
        args: Target function arguments as a dict (excluding ``reason``).

    Returns:
        Structured JSON response from the target function.
    """
    family = (family or "").lower().strip()
    command = (command or "").lower().strip()
    call_args: dict[str, Any] = args or {}

    err = _validate_ax_inputs(reason, family, command)
    if err is not None:
        return err

    if command == "help":
        return _build_help(family)
    if family == "help":
        return _build_help(None)

    resolved = _resolve_entry(reason, family, command)
    if isinstance(resolved, str):
        return resolved
    loader, inject_action = resolved

    fn = _load_target(loader, reason, family, command)
    if isinstance(fn, str):
        return fn

    kwargs: dict[str, Any] = {"reason": reason, **call_args}
    if inject_action:
        kwargs["action"] = command
    kwargs = _strip_unknown_kwargs(fn, kwargs, family, command)

    return await _invoke_target(fn, kwargs, reason, family, command)
