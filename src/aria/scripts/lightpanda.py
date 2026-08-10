"""Download and manage Lightpanda browser binaries from GitHub releases.

This module provides functionality to download and manage Lightpanda
binaries from the lightpanda-io GitHub releases. Lightpanda is a
lightweight headless browser with CDP support for Playwright automation.

Example:
    ```python
    from pathlib import Path
    from aria.scripts.lightpanda import download_lightpanda

    # Download the nightly release to bin/lightpanda/
    download_lightpanda(bin_dir=Path("bin/lightpanda"))
    ```
"""

import platform
import stat
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console(width=200)
error_console = Console(stderr=True, style="bold red", width=200)

# GitHub repository for Lightpanda
GITHUB_REPO = "lightpanda-io/browser"
# Nightly releases don't have a 'latest' tag, use nightly directly
GITHUB_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/download/nightly"


def download_lightpanda(bin_dir: Path, version: str | None = None) -> Path:
    """Download Lightpanda binary for current platform.

    Args:
        bin_dir: Directory to install the binary to.
        version: Specific version tag (default: nightly).

    Returns:
        Path to the downloaded binary.

    Raises:
        RuntimeError: If download fails.

    Steps:
        1. Determine platform-specific asset name
        2. Download binary from GitHub releases
        3. Make executable (chmod +x)
        4. No post-install step needed (Lightpanda IS the browser)
    """
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Determine version (default to nightly)
    tag = version or "nightly"
    logger.info(f"Downloading Lightpanda {tag}")

    # Get platform-specific asset name
    asset_name = _get_platform_asset_name()
    if not asset_name:
        raise RuntimeError(
            f"No Lightpanda binary available for platform: "
            f"{platform.system()}-{platform.machine()}"
        )

    # Build download URL
    if tag == "nightly":
        download_url = f"{GITHUB_RELEASE_URL}/{asset_name}"
    else:
        base = f"https://github.com/{GITHUB_REPO}/releases/download"
        download_url = f"{base}/{tag}/{asset_name}"

    # Binary path (always named 'lightpanda' regardless of download name)
    binary_path = bin_dir / "lightpanda"

    # Download the binary
    console.print(f"[cyan]Downloading[/cyan] {asset_name}...")
    _download_file(download_url, binary_path)

    # Make executable on Unix
    if platform.system() != "Windows":
        current_mode = binary_path.stat().st_mode
        binary_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    console.print(f"[green]✓[/green] Downloaded to {binary_path}")
    console.print("[green]✓[/green] Lightpanda ready (no Chromium download needed)")

    return binary_path


def _get_platform_asset_name() -> str | None:
    """Get the platform-specific asset name for Lightpanda.

    Returns:
        Asset name string, or None if platform is not supported.

    Maps platform.system() and platform.machine() to asset names:
        - Linux x86_64 -> lightpanda-x86_64-linux
        - Linux aarch64 -> lightpanda-aarch64-linux
        - macOS x86_64 -> lightpanda-x86_64-macos
        - macOS aarch64 -> lightpanda-aarch64-macos
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if "aarch64" in machine or "arm64" in machine:
            return "lightpanda-aarch64-linux"
        else:
            return "lightpanda-x86_64-linux"
    elif system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return "lightpanda-aarch64-macos"
        else:
            return "lightpanda-x86_64-macos"
    else:
        return None


def _download_file(url: str, dest: Path) -> None:
    """Download a file from URL to destination path with progress bar.

    Args:
        url: URL to download from.
        dest: Destination file path.

    Raises:
        RuntimeError: If download fails.
    """
    import sys

    in_tty = sys.stdout.isatty()
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/octet-stream"}
        )
        response = urllib.request.urlopen(req, timeout=300)

        # Get file size if available
        total_size = int(response.headers.get("Content-Length", 0))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            disable=not in_tty,
        ) as progress:
            task = progress.add_task(
                "Downloading", total=total_size if total_size > 0 else None
            )

            with open(dest, "wb") as f:
                downloaded = 0
                chunk_size = 8192
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress.update(task, completed=downloaded)
                    else:
                        # Update with bytes downloaded even without total
                        progress.update(
                            task,
                            completed=downloaded,
                            total=downloaded + chunk_size,
                        )

    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Failed to download from {url}: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to download from {url}: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")
