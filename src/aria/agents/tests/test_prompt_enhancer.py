"""Contract tests for the PromptEnhancerAgent prompt wiring."""

from aria.agents.prompt_enhancer import PromptEnhancerAgent


class TestStripIrrelevantExtras:
    """The enhancer never executes commands — its extras must drop binary lists."""

    def test_strips_binaries_bullets_only(self):
        extras = (
            "Runtime context (internal reference — do not reproduce it in replies):\n"
            "\n"
            "- **Date**: August 16th 2026 17:00 (CEST)\n"
            "- **Managed binaries**: `/home/d/.aria/bin` (on $PATH) — docling, vllm\n"
            "- **Venv CLIs**: extra CLI tools are installed in the active venv — "
            "list via `ax check extras`.\n"
        )
        stripped = PromptEnhancerAgent._strip_irrelevant_extras(extras)
        assert "Managed binaries" not in stripped
        assert "Venv CLIs" not in stripped
        assert "- **Date**: August 16th 2026" in stripped
