"""Unified web search tool.

Routes to SearXNG when SEARXNG_URL is configured, otherwise DuckDuckGo.
Both backends return their own structured JSON; this wrapper only selects
which one to call and catches unexpected exceptions.
"""

from os import getenv

from loguru import logger

from aria.tools import (
    Reason,
    get_function_name,
    log_tool_call,
    tool_error_response,
)


@log_tool_call
def web_search(
    reason: Reason,
    query: str,
    category: str | None = None,
    time_range: str | None = None,
    max_results: int | None = 5,
) -> str:
    """Search the web for information using the best available backend.

    When to use:
        - Use this when you need to find information on the internet
          (e.g., documentation, news, tutorials, facts).
        - Use this as the first step when researching a topic online.
        - Do NOT use this to download files — use `download`.
        - Do NOT use this to browse a specific website — use `visit_url`.

    Why:
        Auto-selects the best available search backend (SearXNG if
        configured, otherwise DuckDuckGo). SearXNG supports category
        and time-range filters for more targeted results.

    Args:
        reason: Required. Brief explanation of why you are searching.
        query: Search query string.
        category: Optional category filter (SearXNG only): general,
            files, news, videos, images.
        time_range: Optional freshness filter (SearXNG only): day,
            week, month, year.
        max_results: Maximum results (default: 5).

    Returns:
        JSON with results, error if failed.
        Use `visit_url` or `download` to get full content from URLs.

    Important:
        - category and time_range only work when SEARXNG_URL is set.
        - Returns URLs, not page content — use `visit_url` or `download`
          to get full content.
    """
    max_results_value = max_results if max_results is not None else 5

    try:
        if getenv("SEARXNG_URL", "").strip():
            from aria.tools.search.searxng import searxng_web_search

            return searxng_web_search(
                reason=reason,
                query=query,
                category=(category or "general"),  # type: ignore[arg-type]
                time_range=(time_range or ""),  # type: ignore[arg-type]
                max_results=max_results_value,
            )

        from aria.tools.search.duckduckgo import duckduckgo_web_search

        return duckduckgo_web_search(
            reason=reason,
            query=query,
            max_results=max_results_value,
        )
    except Exception as exc:
        logger.error(f"web_search failed: {exc}")
        return tool_error_response(get_function_name(), reason, exc)
