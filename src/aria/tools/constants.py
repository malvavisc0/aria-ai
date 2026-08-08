"""
Shared constants across all aria2 tools.

This module contains constants that are used by multiple tool modules,
providing a single source of truth for common configuration.
"""

import os
from pathlib import Path

from aria.config.folders import Workspace

# ============================================================================
# Directory Configuration
# ============================================================================

# Base directory for all file operations (agent workspace)
BASE_DIR = Path(os.environ.get("TOOLS_DATA_FOLDER", str(Workspace.path))).resolve()
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Derived directories
CODE_DIR = BASE_DIR / "code"
CODE_DIR.mkdir(exist_ok=True)

DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ============================================================================
# Size and Timeout Limits
# ============================================================================

# Maximum file size for processing (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Default timeout for operations (seconds)
DEFAULT_TIMEOUT = int(os.environ.get("ARIA_DEFAULT_TIMEOUT", "30"))

# Maximum timeout limit (seconds) — configurable for long builds/downloads
MAX_TIMEOUT = int(os.environ.get("ARIA_MAX_TIMEOUT", "600"))

# ============================================================================
# Network Configuration
# ============================================================================

# Network request timeout (seconds)
NETWORK_TIMEOUT = 10
