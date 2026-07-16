"""HTTP request tool for making API calls."""

from uuid import uuid4

import httpx
from loguru import logger

from aria.tools import Reason, tool_response
from aria.tools.constants import (
    BASE_DIR,
    DEFAULT_TIMEOUT,
    MAX_TIMEOUT,
)
from aria.tools.decorators import log_tool_call

HTTP_OUTPUT_DIR = BASE_DIR / "http"
HTTP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _persist_http_body(response: httpx.Response) -> tuple[str, int, str]:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    suffix = ".json" if "json" in content_type else ".txt"
    file_path = HTTP_OUTPUT_DIR / f"response_{uuid4().hex}{suffix}"
    body_text = response.text
    file_path.write_text(body_text, encoding="utf-8")
    return str(file_path), len(body_text), content_type or "text/plain"


# Allowed HTTP methods
_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


@log_tool_call
def http_request(
    reason: Reason,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int | None = None,
) -> str:
    """Make HTTP requests to web APIs with redirect following.

    When to use:
        - Call REST APIs, fetch JSON data, or interact with web services.
        - Do NOT use for browsing websites — use `visit_url`.
        - Do NOT use for downloading files — use `download`.

    Args:
        reason: Required. Brief explanation of why you are making this request.
        method: GET | POST | PUT | DELETE | PATCH | HEAD | OPTIONS.
        url: The URL to request.
        headers: Optional request headers (dict).
        body: Optional request body string (for POST/PUT/PATCH).
        timeout: Timeout in seconds (default: 30, max: 300).

    Returns:
        JSON with status_code, headers, final url, saved body file path.
    """
    method = method.upper().strip()

    if method not in _ALLOWED_METHODS:
        return tool_response(
            tool="http_request",
            reason=reason,
            data={
                "error": (
                    f"Method '{method}' not allowed. "
                    f"Use: {', '.join(sorted(_ALLOWED_METHODS))}"
                ),
            },
        )

    actual_timeout = min(
        timeout if timeout is not None else DEFAULT_TIMEOUT,
        MAX_TIMEOUT,
    )

    try:
        with httpx.Client(
            timeout=actual_timeout,
            follow_redirects=True,
        ) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

        body_file, body_size, content_type = _persist_http_body(response)

        return tool_response(
            tool="http_request",
            reason=reason,
            data={
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "url": str(response.url),
                "body_file": body_file,
                "body_size": body_size,
                "content_type": content_type,
            },
        )

    except httpx.TimeoutException:
        return tool_response(
            tool="http_request",
            reason=reason,
            data={"error": f"Request timed out after {actual_timeout}s"},
        )
    except httpx.ConnectError as exc:
        return tool_response(
            tool="http_request",
            reason=reason,
            data={"error": f"Connection failed: {exc}"},
        )
    except Exception as exc:
        logger.exception("HTTP request failed")
        return tool_response(
            tool="http_request",
            reason=reason,
            data={"error": f"Request failed: {exc}"},
        )
