"""
Constants for search and download operations.

This module contains constants specific to URL downloading and content
processing. For shared constants, imports from aria.tools.constants.
"""

from aria.tools.constants import DOWNLOADS_DIR, MAX_FILE_SIZE
from aria.tools.constants import NETWORK_TIMEOUT as TIMEOUT

MAX_RETRIES = 3

# Re-export for backward compatibility
__all__ = [
    "BINARY_CONTENT_TYPES",
    "DOWNLOADS_DIR",
    "HTML_CONTENT_TYPES",
    "MAX_FILE_SIZE",
    "MAX_RETRIES",
    "SUPPORTED_FORMATS",
    "TIMEOUT",
    "USER_AGENTS",
]

# Supported output formats
SUPPORTED_FORMATS = ["markdown", "text", "html", "binary", "xml", "auto"]

# File types that should be processed with html2text
HTML_CONTENT_TYPES = [
    "text/html",
    "application/xhtml+xml",
    "text/xml",
    "application/xml",
]

# Binary file types that should be saved as-is
BINARY_CONTENT_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "image/",
    "video/",
    "audio/",
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "application/octet-stream",
]

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
]
