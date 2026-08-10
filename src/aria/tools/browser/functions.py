"""Browser automation tools using Lightpanda with Playwright CDP.

Tools for:
1. Visiting URLs and getting page content
2. Clicking elements (accept cookies, pagination, etc.)

The browser is started automatically when the Aria server starts.
Lightpanda must be installed first:
    aria lightpanda download

Example:
    ```python
    from aria.tools.browser import visit_url, browser_click

    # Visit a URL and get page content
    result = visit_url("Reading documentation", "https://example.com")

    # Click an element by CSS selector
    result = browser_click("Accepting cookies", "button.accept")
    ```
"""

from aria.tools import Reason, get_function_name
from aria.tools.browser.manager import get_browser_manager
from aria.tools.decorators import log_tool_call


def _get_manager():
    """Get the browser manager, raising if unavailable."""
    manager = get_browser_manager()
    if manager is None:
        raise RuntimeError(
            "Browser is not available. Either Lightpanda is not installed "
            "(run 'aria lightpanda download') or the browser "
            "failed to start."
        )
    if not manager.is_running:
        raise RuntimeError(
            "Browser is not running. It should have been started "
            "during app startup. Check the server logs for errors."
        )
    return manager


@log_tool_call
async def visit_url(reason: Reason, url: str) -> str:
    """Visit a URL in the headless browser and capture rendered content.

    This is the PRIMARY tool for reading web page content. Always prefer
    it over `download` for HTML pages: it renders JavaScript, follows
    consent flows, and gets through anti-bot protection that a plain HTTP
    fetch cannot.

    Only use `download` instead when:
        - The URL points to a binary file (PDF, image, archive, media), or
        - `visit_url` fails and you need the raw content as a fallback.

    Do not use this for plain API/JSON calls.

    Args:
        reason: Required. Brief explanation of why you are visiting this URL.
        url: URL to navigate to.

    Returns:
        JSON with page metadata and a saved content file path.
    """
    manager = _get_manager()
    return await manager.navigate(
        url,
        tool=get_function_name(),
        reason=reason,
    )


@log_tool_call
async def browser_click(
    reason: Reason,
    selector: str,
) -> str:
    """Click an element on the current browser page.

    Use this after ``visit_url`` for consent banners, pagination, or reveal
    interactions. An active page must already exist.

    Args:
        reason: Required. Brief explanation of why you are clicking this element.
        selector: CSS selector for the target element.

    Returns:
        JSON with updated page metadata after the click.
    """
    manager = _get_manager()
    return await manager.click(
        selector,
        tool=get_function_name(),
        reason=reason,
    )


@log_tool_call
async def browser_close(reason: Reason) -> str:
    """Close the current browser page.

    When to use:
        - Use this after you're done interacting with a page that was
          visited with `visit_url`.
        - Closes the current page by navigating to about:blank. The
          browser itself stays running for future use.

    Args:
        reason: Required. Brief explanation of why you are closing the page.

    Returns:
        JSON confirming the page was closed.
    """
    manager = _get_manager()
    return await manager.close_page(
        tool=get_function_name(),
        reason=reason,
    )
