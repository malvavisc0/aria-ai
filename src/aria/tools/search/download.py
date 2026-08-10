"""Download and convert content from a URL."""

from aria.tools import (
    Reason,
    get_function_name,
    log_tool_call,
    tool_error_response,
    tool_success_response,
)
from aria.tools.search._download_internals import (
    _fetch_file,
    _is_html_content,
    _save_content_to_file,
    _validate_format,
    _validate_url,
)
from aria.tools.search.constants import DOWNLOADS_DIR, MAX_FILE_SIZE


class URLDownloadError(Exception):
    """Custom exception for URL download errors.

    Raised when there are issues with downloading content from a URL,
    such as invalid URLs, network timeouts, or HTTP errors.
    """


class ContentParsingError(Exception):
    """Custom exception for content parsing errors.

    Raised when there are issues processing or converting content after
    downloading.
    """


@log_tool_call
def download(
    reason: Reason,
    url: str,
    output: str | None = "auto",
    custom_headers: dict[str, str] | None = None,
    max_size: int | None = None,
    convert_to_markdown: bool = False,
) -> str:
    """Download binary files and raw content from URLs (PDFs, images, archives, etc.).

    When to use:
        - Use this to download binary files: PDFs, images, archives,
          data files, audio/video, and other raw content.
        - Use this for direct file URLs where you need the bytes saved
          to disk.
        - For reading web pages, prefer `visit_url` — it renders
          JavaScript and handles anti-bot protection. Only fall back to
          this tool (with convert_to_markdown=True) when `visit_url`
          fails on an HTML page.
        - Do NOT use this to browse websites interactively — use
          `visit_url`.
        - Do NOT use this to search the web — use `web_search` first
          to find URLs.
        - Do NOT use this for YouTube transcripts — use
          `get_youtube_video_transcription` instead.

    Why:
        Provides a persistence-first download mechanism that saves files
        to disk and returns metadata. Best suited for binary/raw
        artifacts; HTML retrieval should go through `visit_url` first.

    Args:
        reason: Required. Brief explanation of why you are downloading this file.
        url: Direct URL to the file.
        output: Format — auto/markdown/text/binary (default: "auto").
        custom_headers: Optional HTTP headers.
        max_size: Max bytes to download (default: 5 MB).
        convert_to_markdown: Convert HTML content to markdown
            (default: False). Only relevant for the `visit_url` fallback case.

    Returns:
        JSON with file_path and metadata about the saved artifact.
        Content is persisted to disk and should be read explicitly from
        the returned file paths.

    Important:
        - Files are saved to disk; the response contains the file path.
        - This is a fallback for HTML pages; reach for `visit_url` first.
          If you do fetch HTML here, set convert_to_markdown=True to
          persist a markdown version alongside the saved source file.
        - Large files are rejected if they exceed max_size.
    """
    try:
        validated_url = _validate_url(url)
        output_value = output or "auto"
        validated_format = _validate_format(output_value)
        max_size_value = MAX_FILE_SIZE if max_size is None else max_size

        download_path_value = str(DOWNLOADS_DIR)

        response_data, content_type, filename = _fetch_file(
            validated_url,
            custom_headers=custom_headers,
            max_size=max_size_value,
        )

        # Request markdown persistence through the save layer
        if convert_to_markdown and _is_html_content(content_type or ""):
            validated_format = "markdown"

        file_path, metadata = _save_content_to_file(
            response_data,
            validated_url,
            content_type or "application/octet-stream",
            validated_format,
            original_filename=filename,
            download_path=download_path_value,
        )

        result_data = {"file_path": file_path, "metadata": metadata}

        return tool_success_response(
            get_function_name(),
            reason,
            result_data,
        )

    except URLDownloadError as exc:
        return tool_error_response(get_function_name(), reason, exc)
    except ContentParsingError as exc:
        return tool_error_response(get_function_name(), reason, exc)
    except Exception as exc:
        return tool_error_response(get_function_name(), reason, exc)
