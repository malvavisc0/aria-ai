"""Lightpanda browser lifecycle management via Playwright CDP.

The LightpandaManager follows the same pattern as LlamaCppServerManager:
- Started during on_app_startup() if the binary is available
- Stopped during on_app_shutdown()
- Agents use browser tools without worrying about lifecycle

Example:
    ```python
    from aria.tools.browser.manager import (
        LightpandaManager,
        set_browser_manager,
    )

    # During app startup
    manager = LightpandaManager(binary_path, port=9222)
    if await manager.start():
        set_browser_manager(manager)

    # During app shutdown
    await manager.stop()
    set_browser_manager(None)
    ```
"""

import asyncio
import hashlib
import subprocess
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import Browser, Page, Playwright, async_playwright

from aria.tools import tool_error_response, tool_success_response
from aria.tools.browser.constants import (
    BROWSER_COMMAND_TIMEOUT,
    BROWSER_CONTENT_DIR,
    DEFAULT_WAIT_STRATEGY,
    LIGHTPANDA_DEFAULT_PORT,
)


# Module-level singleton — set during app startup
class _BrowserManagerHolder:
    manager: Optional["LightpandaManager"] = None


_holder = _BrowserManagerHolder()


def _build_content_filepath(url: str, action: str) -> Path:
    """Build a stable, timestamped path for persisted page content."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{action}_{digest}.txt"
    return BROWSER_CONTENT_DIR / filename


def get_browser_manager() -> Optional["LightpandaManager"]:
    """Get the global LightpandaManager instance.

    Returns None if Lightpanda is not installed or not started.
    """
    return _holder.manager


def set_browser_manager(manager: Optional["LightpandaManager"]) -> None:
    """Set the global LightpandaManager instance.

    Called from on_app_startup() and on_app_shutdown().
    """
    _holder.manager = manager


class LightpandaManager:
    """Manages Lightpanda browser lifecycle via CDP + Playwright.

    Started during on_app_startup(), stopped during on_app_shutdown().
    Agents use browser tools without worrying about lifecycle.

    The manager starts Lightpanda in serve mode, which creates a CDP
    endpoint that Playwright connects to for browser automation.

    Attributes:
        _binary: Path to the Lightpanda binary.
        _port: CDP port for Lightpanda serve.
        _process: Subprocess running Lightpanda serve.
        _playwright: Playwright instance.
        _browser: Connected Browser instance.
        _page: Current Page instance.
    """

    def __init__(self, binary_path: Path, port: int = LIGHTPANDA_DEFAULT_PORT):
        """Initialize the Lightpanda manager.

        Args:
            binary_path: Path to the Lightpanda binary.
            port: CDP port for Lightpanda serve (default: 9222).
        """
        self._binary = binary_path
        self._port = port
        self._process: subprocess.Popen | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        # Serialise all page operations — Lightpanda serves a single page
        # and concurrent navigations destroy each other's execution context.
        self._page_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Start Lightpanda serve and connect Playwright via CDP.

        This starts the Lightpanda process in serve mode, waits for
        the CDP endpoint to be ready, then connects Playwright.

        Returns:
            True if started successfully, False otherwise.
        """
        try:
            cmd = [
                str(self._binary),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
            ]
            logger.debug(f"Starting Lightpanda: {' '.join(cmd)}")

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if not await self._wait_for_cdp():
                logger.error("Lightpanda CDP endpoint did not become ready")
                self._cleanup_process()
                return False

            self._playwright = await async_playwright().start()
            cdp_url = f"http://127.0.0.1:{self._port}"
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)

            # Lightpanda workaround: ignore SSL errors
            context = await self._browser.new_context(ignore_https_errors=True)
            self._page = await context.new_page()

            logger.info(f"Lightpanda browser started on port {self._port}")
            return True

        except Exception as e:
            logger.error(f"Failed to start Lightpanda: {e}")
            await self.stop()
            return False

    async def stop(self) -> None:
        """Close Playwright, terminate Lightpanda process.

        Called from on_app_shutdown().
        """
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping Playwright: {e}")
            finally:
                self._playwright = None

        self._cleanup_process()
        self._page = None
        logger.info("Lightpanda browser stopped")

    def _cleanup_process(self) -> None:
        """Terminate the Lightpanda subprocess."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except Exception as e:
                logger.warning(f"Error terminating Lightpanda: {e}")
            finally:
                self._process = None

    async def _wait_for_cdp(self, timeout: float = 15.0) -> bool:
        """Wait for the CDP endpoint to be ready.

        Polls the ``/json/version`` HTTP endpoint rather than just
        checking that the TCP port is open.  This avoids a race where
        the port is bound but the HTTP handler is not yet serving.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if CDP is ready, False if timeout.
        """
        import urllib.request

        url = f"http://127.0.0.1:{self._port}/json/version"
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        while loop.time() - start_time < timeout:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=2)
                )
                logger.debug("CDP endpoint is ready")
                return True
            except Exception:
                pass
            await asyncio.sleep(0.3)

        return False

    # ------------------------------------------------------------------
    # Page state helpers
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Check if the browser is running."""
        return (
            self._process is not None
            and self._browser is not None
            and self._page is not None
        )

    async def _ensure_page(self) -> bool:
        """Ensure a valid page exists, restarting browser if needed.

        Returns:
            True if a valid page is available, False otherwise.
        """
        if self._is_page_valid():
            return True

        logger.warning("Browser page invalid, attempting to restart...")
        await self.stop()

        if await self.start():
            logger.info("Browser restarted successfully")
            return True

        logger.error("Failed to restart browser")
        return False

    def _is_page_valid(self) -> bool:
        """Check if the page is still valid and not closed."""
        try:
            return self._page is not None and not self._page.is_closed()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _success(self, data: dict, *, tool: str = "", reason: str = "") -> str:
        """Create a Standard Envelope success JSON response."""
        return tool_success_response(tool, reason, data)

    def _error(
        self,
        message: str,
        *,
        recovery: bool = False,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Create a Standard Envelope error JSON response."""
        exc = RuntimeError(message)
        if recovery:
            exc.recoverable = True  # type: ignore[attr-defined]
            exc.how_to_fix = (  # type: ignore[attr-defined]
                "Browser crashed. Restarted. Retry."
            )
        return tool_error_response(tool=tool, reason=reason, exc=exc)

    def _persist_content(self, content: str, url: str, action: str) -> Path:
        """Write content to a timestamped file and return the path.

        Args:
            content: Text content to persist.
            url: URL the content came from (used for filename hash).
            action: Action label (e.g. "open", "click").

        Returns:
            Path to the written file.
        """
        path = _build_content_filepath(url, action)
        path.write_text(content, encoding="utf-8")
        return path

    async def _safe_title(self) -> str:
        """Get page title with fallback to 'Unknown'."""
        try:
            if self._is_page_valid():
                return await self._page.title()  # type: ignore[union-attr]
        except Exception:
            pass
        return "Unknown"

    def _content_response(
        self,
        content: str,
        url: str,
        title: str,
        content_path: Path,
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Build the standard content JSON response.

        Args:
            content: Page text content.
            url: Current page URL.
            title: Page title.
            content_path: Path where content was persisted.
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            JSON string with page metadata.
        """
        return self._success(
            {
                "url": url,
                "title": title,
                "content_file": str(content_path),
                "content_preview": (
                    content[:500] + "..." if len(content) > 500 else content
                ),
                "content_size": len(content),
            },
            tool=tool,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Recovery wrapper
    # ------------------------------------------------------------------

    async def _with_recovery(
        self,
        action_name: str,
        fn: Callable[[Page], Awaitable[str]],
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Run *fn* with page validation, serialisation, and crash recovery.

        All page operations are serialised through ``_page_lock`` because
        Lightpanda serves a single page — concurrent navigations destroy
        each other's execution context.

        Ensures a valid page before calling *fn(page)*. If *fn* raises
        and the page has crashed, the browser is restarted and a
        recovery error is returned so the caller can retry.

        Args:
            action_name: Human-readable label for log messages.
            fn: Async callable that receives the current Page and
                returns a JSON string result.
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            JSON string — either the result of *fn* or an error.
        """
        async with self._page_lock:
            if not await self._ensure_page():
                return self._error("Browser not available", tool=tool, reason=reason)

            try:
                return await fn(self._page)  # type: ignore[arg-type]
            except Exception as e:
                logger.error(f"{action_name} error: {e}")
                if not self._is_page_valid():
                    logger.warning(
                        f"Browser crashed during {action_name}, attempting restart..."
                    )
                    if await self._ensure_page():
                        return self._error(
                            str(e), recovery=True, tool=tool, reason=reason
                        )
                return self._error(
                    f"{e} — Use the download tool as a fallback.",
                    tool=tool,
                    reason=reason,
                )

    # ------------------------------------------------------------------
    # Browser actions
    # ------------------------------------------------------------------

    async def navigate(
        self,
        url: str,
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Navigate to URL and return rendered content.

        Args:
            url: URL to navigate to.
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            JSON string with page content and metadata.
        """

        async def _do_navigate(page: Page) -> str:
            timeout_ms = BROWSER_COMMAND_TIMEOUT * 1000
            await page.goto(
                url,
                timeout=timeout_ms,
                wait_until=DEFAULT_WAIT_STRATEGY,
            )
            await page.wait_for_load_state(DEFAULT_WAIT_STRATEGY, timeout=timeout_ms)

            content = await self._get_text_content(page)

            if self._is_navigation_failed(content, page.url):
                fail_reason = content if content else "Navigation failed"
                logger.error(f"Navigation failed: {fail_reason}")
                return self._error(fail_reason, tool=tool, reason=reason)

            content_path = self._persist_content(content, page.url, "visit")
            title = await self._safe_title()
            return self._content_response(
                content,
                page.url,
                title,
                content_path,
                tool=tool,
                reason=reason,
            )

        return await self._with_recovery(
            "navigate", _do_navigate, tool=tool, reason=reason
        )

    async def click(
        self,
        selector: str,
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Click element by CSS selector and return updated content.

        Args:
            selector: CSS selector for element to click.
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            JSON string with updated page content.
        """

        async def _do_click(page: Page) -> str:
            timeout_ms = BROWSER_COMMAND_TIMEOUT * 1000
            await page.click(selector, timeout=timeout_ms)
            await page.wait_for_load_state(DEFAULT_WAIT_STRATEGY, timeout=timeout_ms)

            content = await self._get_text_content(page)
            content_path = self._persist_content(content, page.url, "click")
            title = await self._safe_title()
            return self._content_response(
                content,
                page.url,
                title,
                content_path,
                tool=tool,
                reason=reason,
            )

        return await self._with_recovery("click", _do_click, tool=tool, reason=reason)

    async def close_page(
        self,
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Close the current page by navigating to about:blank.

        Lightpanda is a single-page browser, so "closing" means
        navigating to a blank page. The browser stays running.

        Args:
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            JSON string confirming the page was closed.
        """

        async def _do_close(page: Page) -> str:
            timeout_ms = BROWSER_COMMAND_TIMEOUT * 1000
            await page.goto(
                "about:blank",
                timeout=timeout_ms,
                wait_until="commit",
            )
            return self._success(
                {
                    "status": "closed",
                    "message": "Page closed (navigated to about:blank)",
                },
                tool=tool,
                reason=reason,
            )

        return await self._with_recovery(
            "close_page", _do_close, tool=tool, reason=reason
        )

    async def get_page_content(
        self,
        *,
        tool: str = "",
        reason: str = "",
    ) -> str:
        """Get current page content as clean text.

        Args:
            tool: Tool name for the response envelope.
            reason: Agent reason for the response envelope.

        Returns:
            Page content as text, or error JSON if unavailable.
        """

        async def _do_get_content(page: Page) -> str:
            return await self._get_text_content(page)

        return await self._with_recovery(
            "get_page_content", _do_get_content, tool=tool, reason=reason
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_navigation_failed(content: str, url: str) -> bool:
        """Check if navigation produced valid content.

        Args:
            content: The page content to check.
            url: The current page URL.

        Returns:
            True if navigation failed, False otherwise.
        """
        if not content or not content.strip():
            return True
        if url == "about:blank":
            return True
        error_patterns = [
            "Navigation failed",
            "Navigation failedReason:",
            "net::ERR_",
            "This page cannot be loaded",
        ]
        return any(pattern in content for pattern in error_patterns)

    @staticmethod
    async def _get_text_content(page: Page) -> str:
        """Extract cleaned page text content.

        Removes script, style, nav, footer, and other non-content elements,
        then collapses whitespace. Falls back to raw HTML on evaluation errors.
        """
        try:
            content = await page.evaluate(
                """
                () => {
                    const clean = (root) => {
                        if (!root) return '';
                        const clone = root.cloneNode(true);
                        const remove = [
                            'script',
                            'style',
                            'noscript',
                            'nav',
                            'footer',
                            'aside',
                            '[role="navigation"]',
                            '[aria-label*="cookie" i]',
                            '[class*="cookie" i]',
                            '[id*="cookie" i]',
                            '[class*="subscribe" i]',
                            '[class*="newsletter" i]',
                            '[class*="related" i]',
                            '[class*="recommend" i]',
                            '[class*="share" i]',
                            '[class*="social" i]',
                            '[class*="comment" i]'
                        ];
                        remove.forEach(sel => {
                            clone
                                .querySelectorAll(sel)
                                .forEach(el => el.remove());
                        });
                        return clone.innerText || clone.textContent || '';
                    };

                    return clean(document.body);
                }
                """,
            )
            lines = (line.strip() for line in content.splitlines())
            return "\n".join(line for line in lines if line)

        except Exception as e:
            logger.warning(f"Error getting page content: {e}")
            return await page.content()
