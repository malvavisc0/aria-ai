"""URL classification: file download vs website browsing.

Provides a single ``classify_url()`` function that inspects a URL's path
extension and, if needed, sends a HEAD request to determine the
Content-Type.  The result drives the unified ``aria search fetch`` CLI
command so that Aria never has to decide between ``download`` and
``visit_url`` — the CLI routes automatically.
"""

import enum
from urllib.parse import urlparse

import httpx

# Extensions that always indicate a downloadable file
_FILE_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".svg",
    ".webp",
    ".ico",
    ".mp3",
    ".mp4",
    ".avi",
    ".mkv",
    ".wav",
    ".flac",
    ".ogg",
    ".csv",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".exe",
    ".dmg",
    ".deb",
    ".rpm",
    ".AppImage",
    ".whl",
    ".egg",
    ".iso",
}

# Content-Types that indicate a downloadable file
_FILE_CONTENT_TYPES = {
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/octet-stream",
    "application/vnd.openxmlformats-officedocument",
}

# Content-Types that indicate a website
_WEBSITE_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


class URLType(enum.Enum):
    FILE = "file"
    WEBSITE = "website"


def classify_url(url: str, timeout: float = 5.0) -> URLType:
    """Classify a URL as a file download or a website.

    Strategy:
        1. Check URL path extension against known file types
        2. Send HEAD request and check Content-Type header
        3. Fall back to WEBSITE if ambiguous

    Args:
        url: The URL to classify.
        timeout: HEAD request timeout in seconds.

    Returns:
        ``URLType.FILE`` or ``URLType.WEBSITE``.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Rule 1: Known file extension in URL
    for ext in _FILE_EXTENSIONS:
        if path.endswith(ext):
            return URLType.FILE

    # Rule 2: HEAD request content-type sniffing
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.head(url)
            content_type = (
                resp.headers.get("content-type", "").lower().split(";")[0].strip()
            )

            if any(content_type.startswith(ft) for ft in _FILE_CONTENT_TYPES):
                return URLType.FILE
            if any(content_type.startswith(wt) for wt in _WEBSITE_CONTENT_TYPES):
                return URLType.WEBSITE

            # Binary content types → file
            if content_type.startswith(("image/", "audio/", "video/", "application/")):
                return URLType.FILE
    except (httpx.TimeoutException, httpx.ConnectError, Exception):
        pass  # Fall through to default

    # Rule 3: Default to website (safer — browser can handle both)
    return URLType.WEBSITE
