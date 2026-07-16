"""Browser tool exceptions."""

from aria.tools.errors import ToolError


class BrowserError(ToolError):
    """Base exception for browser operations."""

    code = "BROWSER_ERROR"
    recoverable = True
    how_to_fix = "Check browser state and try again."


class BrowserNotRunningError(BrowserError):
    """Browser process is not running."""

    code = "BROWSER_NOT_RUNNING"
    recoverable = True
    how_to_fix = "Start the browser using the initialization function."


class NavigationTimeoutError(BrowserError):
    """Page navigation timed out."""

    code = "NAVIGATION_TIMEOUT"
    recoverable = True
    how_to_fix = "Try again with a simpler URL or check network connectivity."


class ElementNotFoundError(BrowserError):
    """Element selector not found on page."""

    code = "ELEMENT_NOT_FOUND"
    recoverable = True
    how_to_fix = (
        "Verify the CSS selector is correct and the element exists on the page."
    )


class PageNotOpenError(BrowserError):
    """No page is currently open in the browser."""

    code = "PAGE_NOT_OPEN"
    recoverable = True
    how_to_fix = "Navigate to a URL first using visit_url()."
