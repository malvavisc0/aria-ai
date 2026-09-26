"""Constants for browser automation tools.

This module contains constants specific to browser automation using
Lightpanda with Playwright CDP. For shared constants, imports from
aria.tools.constants.
"""

from aria.config.folders import Workspace

# Timeout for individual browser commands (seconds)
# Long enough for slow pages but not so long that failures waste time
BROWSER_COMMAND_TIMEOUT = 30

# Timeout for navigation commit — server response only, not full render.
NAVIGATION_TIMEOUT = 15

# Default wait strategy after navigation
# "domcontentloaded" is reliable; "networkidle" fails on most modern sites
# because analytics, CDNs, and trackers keep connections open.
DEFAULT_WAIT_STRATEGY = "domcontentloaded"

# Default CDP port for Lightpanda serve
LIGHTPANDA_DEFAULT_PORT = 9222

# Persisted browser page-content captures — stored under ~/.aria/workspace/browser
BROWSER_CONTENT_DIR = Workspace.path / "browser"
BROWSER_CONTENT_DIR.mkdir(parents=True, exist_ok=True)
