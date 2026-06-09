"""Browser automation tools using Lightpanda with Playwright CDP.

Tools for:
1. Opening URLs and getting page content
2. Clicking elements (accept cookies, pagination, etc.)

The browser is started automatically when the Aria server starts.
Lightpanda must be installed first:
    aria lightpanda download

Example:
    ```python
    from aria.tools.browser import open_url, browser_click

    # Open a URL and get page content
    result = open_url("Reading documentation", "https://example.com")

    # Click an element by CSS selector
    result = browser_click("Accepting cookies", "button.accept")
    ```
"""

from pydantic import BaseModel, Field

from aria.tools import Reason, get_function_name
from aria.tools.browser.manager import get_browser_manager
from aria.tools.decorators import log_tool_call


class OpenUrlSchema(BaseModel):
    """Schema exposed to the LLM for open_url."""

    reason: str = Field(
        description="Required. Brief explanation of why you are opening this URL."
    )
    url: str = Field(description="Full URL to open in the headless browser.")
    content_mode: str = Field(
        default="text",
        description=(
            "'text' for plain text/markdown content, "
            "'html' for raw HTML (default: 'text')."
        ),
    )


class BrowserClickSchema(BaseModel):
    """Schema exposed to the LLM for browser_click."""

    reason: str = Field(
        description="Required. Brief explanation of why you are clicking this element."
    )
    selector: str = Field(
        description=(
            "CSS selector or text to identify the element to click "
            "(e.g. '#submit-btn', 'a.more')."
        ),
    )
    content_mode: str = Field(
        default="text",
        description=(
            "'text' for plain text content after click, "
            "'html' for raw HTML (default: 'text')."
        ),
    )


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
async def open_url(reason: Reason, url: str, content_mode: str = "text") -> str:
    """Open a URL in the headless browser and capture rendered content.

    This is the PRIMARY tool for reading web page content. Always prefer
    it over `download` for HTML pages: it renders JavaScript, follows
    consent flows, and gets through anti-bot protection that a plain HTTP
    fetch cannot.

    Only use `download` instead when:
        - The URL points to a binary file (PDF, image, archive, media), or
        - `open_url` fails and you need the raw content as a fallback.

    Do not use this for plain API/JSON calls — use `http` or `download`.

    Args:
        reason: Required. Brief explanation of why you are opening this URL.
        url: URL to navigate to.
        content_mode: ``text`` for cleaned page text or ``article`` for main content.

    Returns:
        JSON with page metadata and a saved content file path.
    """
    manager = _get_manager()
    return await manager.navigate(
        url,
        tool=get_function_name(),
        reason=reason,
        content_mode=content_mode,
    )


@log_tool_call
async def browser_click(
    reason: Reason,
    selector: str,
    content_mode: str = "text",
) -> str:
    """Click an element on the current browser page.

    Use this after ``open_url`` for consent banners, pagination, or reveal
    interactions. An active page must already exist.

    Args:
        reason: Required. Brief explanation of why you are clicking this element.
        selector: CSS selector for the target element.
        content_mode: Extraction mode for the updated page content.

    Returns:
        JSON with updated page metadata after the click.
    """
    manager = _get_manager()
    return await manager.click(
        selector,
        tool=get_function_name(),
        reason=reason,
        content_mode=content_mode,
    )


@log_tool_call
async def browser_close(reason: Reason) -> str:
    """Close the current browser page.

    When to use:
        - Use this after you're done interacting with a page that was
          opened with `open_url`.
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
