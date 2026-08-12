"""First-run setup wizard for Aria.

A QWizard-based guided setup that walks new users through:
1. Connection setup (Local vs Remote)
2. Download dependencies (Lightpanda, embeddings model)
3. Create admin user
4. Finish

The wizard is shown automatically on first run when no users exist.
"""

from aria.gui.wizard.flow import run_wizard, should_show_wizard
from aria.gui.wizard.pages import SetupWizard

__all__ = ["SetupWizard", "run_wizard", "should_show_wizard"]
