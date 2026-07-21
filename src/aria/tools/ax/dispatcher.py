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
            "check, worker."
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

    if not reason:
        return tool_response(
            tool="ax",
            reason="missing_reason",
            data={
                "error": {
                    "code": "missing_reason",
                    "message": "The 'reason' argument is required. Explain why you are calling this tool.",
                    "hint": "Pass a brief reason string, e.g. reason='Search for Python tutorials'.",
                }
            },
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
                        "family": "Tool family: web, knowledge, finance, imdb, http, dev, processes, check, worker",
                        "command": "Subcommand within the family",
                        "args": "Optional arguments dict (exclude 'reason')",
                    },
                }
            },
        )

    if command == "help":
        return _build_help(family)
    if family == "help":
        return _build_help(None)

    family_commands = _DISPATCH.get(family)
    if family_commands is None:
        available = list(_DISPATCH.keys())
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "unknown_family",
                    "message": f"Unknown family: '{family}'",
                    "available_families": available,
                    "hint": "Use command='help' to see all families and commands.",
                }
            },
        )

    entry = family_commands.get(command)
    if entry is None:
        available_cmds = list(family_commands.keys())
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "unknown_command",
                    "message": f"Unknown command: '{command}' in family '{family}'",
                    "available_commands": available_cmds,
                    "hint": f"Use ax(family='{family}', command='help') to see options.",
                }
            },
        )

    loader, inject_action = entry

    try:
        fn = loader()
    except ImportError as exc:
        logger.warning(f"ax dispatch: import failed for {family}.{command}: {exc}")
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "import_error",
                    "message": f"Could not load {family}.{command}: {exc}",
                    "recoverable": False,
                }
            },
        )

    kwargs: dict[str, Any] = {"reason": reason, **call_args}
    if inject_action:
        kwargs["action"] = command

    # Strip kwargs that the target function doesn't accept to avoid
    # TypeError from hallucinated args (e.g. 'timeout', 'mode').
    # Skip filtering if the signature has no params (likely a mock,
    # wrapper, or C function we can't inspect).
    try:
        sig = inspect.signature(fn)
        accepted = set(sig.parameters.keys())
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        # If the function accepts **kwargs, nothing to strip.
        # If the signature is empty (mock / uninspectable), skip.
        if accepted and not has_var_keyword:
            filtered = {k: v for k, v in kwargs.items() if k in accepted}
            dropped = set(kwargs.keys()) - accepted
            if dropped:
                logger.debug(
                    "ax dispatch: stripping unknown args {} for {}.{}",
                    dropped,
                    family,
                    command,
                )
            kwargs = filtered
    except (ValueError, TypeError):
        pass  # Built-in or C function — can't inspect, pass everything.

    # Call the function (handle async targets like browser tools)
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(**kwargs)
        else:
            result = fn(**kwargs)
    except TypeError as exc:
        # Likely wrong arguments — give helpful error
        logger.warning(f"ax dispatch: TypeError calling {family}.{command}: {exc}")
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "invalid_args",
                    "message": str(exc),
                    "hint": "Check the required arguments for this command.",
                    "recoverable": True,
                }
            },
        )
    except AxDispatchError as exc:
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "dispatch_error",
                    "message": str(exc),
                    "recoverable": False,
                }
            },
        )
    except Exception as exc:
        logger.error(
            f"ax dispatch: {family}.{command} raised {type(exc).__name__}: {exc}"
        )
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "execution_error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "recoverable": True,
                }
            },
        )

    return result
