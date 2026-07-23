"""Internal helpers for URL download functionality.

This module contains internal functions used by get_file_from_url.
These are not part of the public API and may change without notice.
"""

import mimetypes
import os
import random
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from loguru import logger

from aria.tools import (
    tool_error_response,
    tool_success_response,
    utc_timestamp,
)
from aria.tools.search.constants import (
    BINARY_CONTENT_TYPES,
    HTML_CONTENT_TYPES,
    MAX_FILE_SIZE,
    MAX_RETRIES,
    SUPPORTED_FORMATS,
    TIMEOUT,
    USER_AGENTS,
)


def _validate_url(url: str) -> str:
    """Validate that a URL is well-formed and uses HTTP or HTTPS protocol."""
    from aria.tools.search.download import URLDownloadError

    if not url:
        raise URLDownloadError("URL cannot be empty")
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise URLDownloadError("Invalid URL format")
        if parsed.scheme not in ["http", "https"]:
            raise URLDownloadError("Only HTTP and HTTPS URLs are supported")
    except Exception as exc:
        raise URLDownloadError(f"URL validation failed: {exc}") from exc
    return url


def _validate_format(output_format: str) -> str:
    """Validate that the requested output format is supported."""
    from aria.tools.search.download import ContentParsingError

    if output_format in SUPPORTED_FORMATS:
        return output_format
    supported = ", ".join(SUPPORTED_FORMATS)
    error = f"Unsupported format '{output_format}'. Supported formats: {supported}"
    raise ContentParsingError(error)


def _is_html_content(content_type: str) -> bool:
    """Check if a content type represents HTML content."""
    return any(html_type in content_type for html_type in HTML_CONTENT_TYPES)


def _is_binary_content(content_type: str) -> bool:
    """Check if a content type represents binary content."""
    return any(binary_type in content_type for binary_type in BINARY_CONTENT_TYPES)


def _get_default_headers() -> dict[str, str]:
    """Generate default HTTP headers to mimic a real browser."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _extract_filename_from_response(response: httpx.Response, url: str) -> str | None:
    """Extract filename from HTTP response headers or URL."""
    content_disp = response.headers.get("content-disposition", "")
    if content_disp:
        match = re.search(r'filename[*]?=(["\']?)(.+?)\1', content_disp)
        if match:
            return os.path.basename(match.group(2))
    parsed_url = urlparse(url)
    if parsed_url.path:
        filename = os.path.basename(parsed_url.path)
        if filename and "." in filename:
            return filename
    return None


def _check_size_limit(size: int, max_size: int) -> None:
    from aria.tools.search.download import URLDownloadError

    if size > max_size:
        raise URLDownloadError(
            f"File size ({size} bytes) exceeds maximum allowed size ({max_size} bytes)"
        )


def _process_response(
    response: httpx.Response, url: str, max_size: int
) -> tuple[str | bytes, str, str | None]:
    content_length = response.headers.get("content-length")
    if content_length:
        _check_size_limit(int(content_length), max_size)

    raw_type = response.headers.get("content-type", "").lower()
    content_type = raw_type.split(";", 1)[0].strip()
    filename = _extract_filename_from_response(response, url)

    if _is_html_content(content_type):
        text_content = response.text
        _check_size_limit(len(text_content.encode("utf-8")), max_size)
        return text_content, content_type, filename

    content = response.content
    _check_size_limit(len(content), max_size)
    return content, content_type, filename


def _retry_delay(attempt: int) -> float:
    return min(2**attempt, 10) + random.uniform(0, 1)


def _fetch_attempt(
    client: httpx.Client, url: str, max_size: int, attempt: int
) -> tuple[str | bytes, str, str | None] | None:
    """Single fetch attempt; returns (content, content_type, filename) or None to retry."""

    if attempt > 0:
        time.sleep(_retry_delay(attempt))

    response = client.get(url)
    response.raise_for_status()
    return _process_response(response, url, max_size)


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in (429, 503)


def _fetch_file(
    url: str,
    custom_headers: dict[str, str] | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> tuple[str | bytes, str, str | None]:
    """Download a file from a URL with simple retry logic."""
    from aria.tools.search.download import URLDownloadError

    last_error = ""
    headers = _get_default_headers()
    if custom_headers:
        headers.update(custom_headers)

    with httpx.Client(
        timeout=httpx.Timeout(TIMEOUT),
        follow_redirects=True,
        headers=headers,
        verify=False,
    ) as client:
        for attempt in range(MAX_RETRIES):
            try:
                result = _fetch_attempt(client, url, max_size, attempt)
                if result is not None:
                    return result
            except httpx.TimeoutException:
                last_error = f"Request timeout (attempt {attempt + 1}/{MAX_RETRIES})"
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_error = f"HTTP error {status}"
                if _is_retryable_http_status(status):
                    time.sleep(2**attempt)
                    continue
                break
            except URLDownloadError:
                raise
            except Exception as exc:
                last_error = f"Request failed: {exc}"
                break

    raise URLDownloadError(
        f"Failed to fetch file after {MAX_RETRIES} attempts: {last_error}"
    )


def _is_markitdown_supported(content_type: str) -> bool:
    """Check if a content type is supported by MarkItDown for conversion."""
    supported_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/csv",
        "application/json",
        "text/xml",
        "application/xml",
    ]
    return any(supported_type in content_type for supported_type in supported_types)


def _auto_detect_format(content_type: str) -> str:
    """Auto-detect the appropriate output format based on content type."""
    if _is_html_content(content_type) or _is_markitdown_supported(content_type):
        return "markdown"
    if _is_binary_content(content_type):
        return "binary"
    return "text"


def _get_file_extension(url: str, content_type: str) -> str:
    """Get the file extension from URL or content type."""
    parsed_url = urlparse(url)
    if parsed_url.path:
        _, ext = os.path.splitext(parsed_url.path)
        if ext:
            return ext
    content_type = (content_type or "").split(";", 1)[0].strip()
    ext = mimetypes.guess_extension(content_type)
    return ext or ".bin"


def _clean_text(text: str) -> str:
    """Clean and normalize text content."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text.strip())
    text = "".join(char for char in text if ord(char) >= 32 or char in "\n\t")
    return text


def _markitdown(content: str | bytes, content_type: str, url: str) -> str:
    """Convert content to markdown using MarkItDown."""
    from markitdown import MarkItDown

    if isinstance(content, str):
        content = content.encode("utf-8")
    file_ext = _get_file_extension(url, content_type)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, f"content{file_ext}")
        with open(temp_file_path, "wb") as temp_file:
            temp_file.write(content)
        result = MarkItDown().convert(temp_file_path).text_content
    return _clean_text(result)


def _create_response(tool: str, reason: str, file_path: str, metadata: dict) -> str:
    """Create a success JSON response."""
    return tool_success_response(
        tool,
        reason,
        {"file_path": file_path, "metadata": metadata},
    )


def _create_error_response(tool: str, reason: str, error_message: str) -> str:
    """Create an error JSON response."""
    return tool_error_response(tool, reason, RuntimeError(error_message))


def _filename_and_ext(filename: str, url: str, content_type: str) -> tuple[str, str]:
    """Derive (base_filename, extension) from a filename, falling back to URL/CT."""
    base = Path(filename).stem or "content"
    ext = Path(filename).suffix or _get_file_extension(url, content_type)
    return base, ext


def _resolve_download_target(
    download_path: str | None,
    original_filename: str | None,
    url: str,
    content_type: str,
) -> tuple[Path, str, str]:
    """Resolve (download_dir, base_filename, file_ext) for a download."""
    if not download_path:
        download_dir = Path(tempfile.mkdtemp(prefix="aria2_download_"))
        return download_dir, "content", _get_file_extension(url, content_type)

    resolved_path = Path(download_path).expanduser().resolve()
    if resolved_path.is_dir() or (
        not resolved_path.suffix and not resolved_path.exists()
    ):
        download_dir = resolved_path
        download_dir.mkdir(parents=True, exist_ok=True)
        if original_filename:
            base, ext = _filename_and_ext(original_filename, url, content_type)
        else:
            url_path = urlparse(url).path
            url_filename = os.path.basename(url_path) if url_path else "content"
            base, ext = _filename_and_ext(url_filename, url, content_type)
        return download_dir, base, ext

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    ext = resolved_path.suffix or _get_file_extension(url, content_type)
    return resolved_path.parent, resolved_path.stem, ext


def _file_metadata(
    url: str,
    content_type: str,
    file_ext: str,
    *,
    format: str,
    parsed: bool,
    file_size: int,
    original_filename: str | None,
    **extra: object,
) -> dict:
    """Build the metadata dict common to every save branch."""
    metadata: dict = {
        "url": url,
        "content_type": content_type,
        "file_size": file_size,
        "file_extension": file_ext,
        "format": format,
        "parsed": parsed,
        "original_filename": original_filename,
        "timestamp": utc_timestamp(),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _save_markitdown_binary(
    content: str | bytes,
    content_type: str,
    url: str,
    file_ext: str,
    base_filename: str,
    download_dir: Path,
    original_filename: str | None,
) -> tuple[str, dict]:
    """Save a MarkItDown-supported binary, attempting a parsed text sidecar."""
    original_file_path = download_dir / f"{base_filename}{file_ext}"
    if isinstance(content, str):
        content = content.encode("utf-8")
    with open(original_file_path, "wb") as f:
        f.write(content)
    try:
        parsed_text = _markitdown(content, content_type, url)
        parsed_file_path = download_dir / f"{base_filename}_parsed.txt"
        with open(parsed_file_path, "w", encoding="utf-8") as f:
            f.write(parsed_text)
        return str(original_file_path), _file_metadata(
            url,
            content_type,
            file_ext,
            format="binary",
            parsed=True,
            file_size=original_file_path.stat().st_size,
            original_filename=original_filename,
            parsed_file_path=str(parsed_file_path),
            parsed_file_size=parsed_file_path.stat().st_size,
        )
    except Exception as e:
        return str(original_file_path), _file_metadata(
            url,
            content_type,
            file_ext,
            format="binary",
            parsed=False,
            file_size=original_file_path.stat().st_size,
            original_filename=original_filename,
            parse_error=str(e),
        )


def _save_plain_binary(
    content: str | bytes,
    content_type: str,
    url: str,
    file_ext: str,
    base_filename: str,
    download_dir: Path,
    original_filename: str | None,
) -> tuple[str, dict]:
    """Save a plain binary file as-is."""
    file_path = download_dir / f"{base_filename}{file_ext}"
    if isinstance(content, str):
        content = content.encode("utf-8")
    with open(file_path, "wb") as f:
        f.write(content)
    return str(file_path), _file_metadata(
        url,
        content_type,
        file_ext,
        format="binary",
        parsed=False,
        file_size=file_path.stat().st_size,
        original_filename=original_filename,
    )


def _save_html_to_markdown(
    content: str,
    content_type: str,
    url: str,
    file_ext: str,
    base_filename: str,
    download_dir: Path,
    original_filename: str | None,
) -> tuple[str, dict]:
    """Save HTML and attempt a markdown conversion sidecar."""
    html_file_path = download_dir / f"{base_filename}{file_ext}"
    with open(html_file_path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        logger.debug(f"Converting HTML to markdown for {url}")
        markdown_content = _markitdown(content, content_type, url)
        logger.debug("HTML to markdown conversion successful")
        markdown_file_path = download_dir / f"{base_filename}.md"
        with open(markdown_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        return str(html_file_path), _file_metadata(
            url,
            content_type,
            file_ext,
            format="html",
            parsed=True,
            file_size=html_file_path.stat().st_size,
            original_filename=original_filename,
            parsed_file_path=str(markdown_file_path),
            parsed_file_size=markdown_file_path.stat().st_size,
        )
    except Exception as e:
        logger.error(f"Failed to convert HTML to markdown: {e}")
        return str(html_file_path), _file_metadata(
            url,
            content_type,
            file_ext,
            format="html",
            parsed=False,
            file_size=html_file_path.stat().st_size,
            original_filename=original_filename,
            parse_error=str(e),
        )


def _save_text(
    content: str,
    content_type: str,
    url: str,
    output_format: str,
    file_ext: str,
    base_filename: str,
    download_dir: Path,
    original_filename: str | None,
) -> tuple[str, dict]:
    """Save text content as html/markdown/text depending on format."""
    if _is_html_content(content_type):
        format_type = "html"
        file_name = f"{base_filename}{file_ext}"
    elif output_format == "markdown":
        format_type = "markdown"
        file_name = f"{base_filename}.md"
        try:
            content = _markitdown(content, content_type, url)
        except Exception as e:
            logger.warning(f"markdown conversion skipped: {e}")
    else:
        format_type = "text"
        file_name = f"{base_filename}{file_ext}"

    file_path = download_dir / file_name
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return str(file_path), _file_metadata(
        url,
        content_type,
        file_ext,
        format=format_type,
        parsed=False,
        file_size=file_path.stat().st_size,
        original_filename=original_filename,
    )


def _save_bytes_fallback(
    content: bytes,
    content_type: str,
    url: str,
    file_ext: str,
    base_filename: str,
    download_dir: Path,
    original_filename: str | None,
) -> tuple[str, dict]:
    """Save non-binary bytes content as a binary file."""
    file_path = download_dir / f"{base_filename}{file_ext}"
    with open(file_path, "wb") as f:
        f.write(content)
    return str(file_path), _file_metadata(
        url,
        content_type,
        file_ext,
        format="binary",
        parsed=False,
        file_size=file_path.stat().st_size,
        original_filename=original_filename,
    )


def _save_content_to_file(
    content: str | bytes,
    url: str,
    content_type: str,
    output_format: str = "auto",
    original_filename: str | None = None,
    download_path: str | None = None,
) -> tuple[str, dict]:
    """Save content to a file on disk and return the file path and metadata."""
    download_dir, base_filename, file_ext = _resolve_download_target(
        download_path, original_filename, url, content_type
    )
    if output_format == "auto":
        output_format = _auto_detect_format(content_type)

    if _is_binary_content(content_type) and _is_markitdown_supported(content_type):
        return _save_markitdown_binary(
            content,
            content_type,
            url,
            file_ext,
            base_filename,
            download_dir,
            original_filename,
        )
    if _is_binary_content(content_type):
        return _save_plain_binary(
            content,
            content_type,
            url,
            file_ext,
            base_filename,
            download_dir,
            original_filename,
        )
    if isinstance(content, str):
        if _is_html_content(content_type) and output_format == "markdown":
            return _save_html_to_markdown(
                content,
                content_type,
                url,
                file_ext,
                base_filename,
                download_dir,
                original_filename,
            )
        return _save_text(
            content,
            content_type,
            url,
            output_format,
            file_ext,
            base_filename,
            download_dir,
            original_filename,
        )
    return _save_bytes_fallback(
        content,
        content_type,
        url,
        file_ext,
        base_filename,
        download_dir,
        original_filename,
    )
