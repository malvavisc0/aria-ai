"""Webserp-backed web search tool.

webserp is a CLI metasearch engine that queries Google, DuckDuckGo, Brave,
Yahoo, Mojeek, Startpage, and Presearch in parallel with browser
impersonation (curl_cffi). It is invoked as a subprocess and its JSON
output is normalised into the standard tool response format.
"""

import json
import subprocess
from typing import Any

from loguru import logger

from aria.tools import (
    Reason,
    get_function_name,
    tool_error_response,
    tool_success_response,
)
from aria.tools.decorators import log_tool_call

_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_RESULTS_DEFAULT = 5


@log_tool_call
def web_search(
    reason: Reason,
    query: str,
    max_results: int = _MAX_RESULTS_DEFAULT,
) -> str:
    """Search the web via webserp and return structured JSON results.

    Args:
        reason: Required. Brief explanation of why you are searching.
        query: Search query text.
        max_results: Maximum results to return (default: 5).

    Returns:
        JSON with `count` and `findings` (url, title, content, engine).
    """
    if not query:
        return tool_error_response(
            get_function_name(), reason, RuntimeError("query cannot be empty")
        )
    if max_results < 1:
        return tool_error_response(
            get_function_name(),
            reason,
            RuntimeError("max_results must be positive"),
        )

    try:
        output = _run_webserp(query=query, max_results=max_results)
        findings = _parse_output(output)
    except Exception as exc:
        logger.error(f"webserp failed: {exc}")
        return tool_error_response(get_function_name(), reason, exc)

    return tool_success_response(
        get_function_name(),
        reason,
        {
            "count": len(findings),
            "findings": findings,
            "params": {"query": query, "max_results": max_results},
            "success": len(findings) > 0,
        },
    )


def _run_webserp(*, query: str, max_results: int) -> str:
    """Invoke the webserp CLI and return stdout as a string."""
    cmd = ["webserp", query, "--max-results", str(max_results)]
    logger.debug(f"Running webserp: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_DEFAULT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"webserp exited with code {result.returncode}: "
            f"{result.stderr.strip() or 'unknown error'}"
        )
    return result.stdout


def _parse_output(output: str) -> list[dict[str, Any]]:
    """Parse webserp's stdout JSON into a list of normalised findings."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"webserp returned invalid JSON: {exc}") from exc

    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("webserp output missing 'results' list")

    findings: list[dict[str, Any]] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        finding = _build_finding(raw)
        if finding is not None:
            findings.append(finding)
    return findings


def _build_finding(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Build a normalised finding from a raw webserp result."""
    url = raw.get("url")
    title = raw.get("title")
    if not url or not title:
        return None

    finding: dict[str, Any] = {"url": url, "title": title}
    if raw.get("content"):
        finding["content"] = raw["content"]
    if raw.get("engine"):
        finding["engine"] = raw["engine"]
    return finding
