"""Tests for load_agent_instructions utility."""

from pathlib import Path

import pytest

from aria.agents.instructions import (
    ALL_BASE_SECTIONS,
    load_agent_instructions,
)


class TestLoadAgentInstructions:
    """Tests for the load_agent_instructions function."""

    def test_loads_aria_instructions(self):
        """Aria instructions should be loaded."""
        result = load_agent_instructions("aria")
        assert "Aria" in result

    def test_loads_core_sections_within_aria(self):
        """Shared and role-specific sections should load for Aria."""
        result = load_agent_instructions("aria")
        assert "Operating Rules" in result
        assert "## Voice" in result  # Aria-specific section
        assert "Delegation" in result  # Aria-specific section

    def test_agent_identity_before_base(self):
        """Agent identity should appear before base sections."""
        result = load_agent_instructions("aria")
        aria_pos = result.index("# Aria")
        core_pos = result.index("## Operating Rules")
        assert aria_pos < core_pos

    def test_extras_appended(self):
        """Extras should appear in the output."""
        result = load_agent_instructions(
            "aria",
            extras="Custom extra note",
        )
        assert "Custom extra note" in result
        assert "Runtime Context" in result

    def test_unknown_agent_returns_empty(self):
        """Unknown agent name should return empty string."""
        result = load_agent_instructions("nonexistent_agent")
        assert result == ""

    def test_all_agents_load_successfully(self):
        """Every known agent should load without error."""
        agents = ["aria", "prompt_enhancer"]
        for agent in agents:
            result = load_agent_instructions(agent)
            assert len(result) > 100, (
                f"Agent '{agent}' instructions too short "
                f"({len(result)} chars) — likely not loading"
            )

    def test_worker_includes_base_sections(self):
        """Worker runtime prompt should include only execution sections."""
        from aria.agents.worker import WorkerAgent

        result = WorkerAgent.get_system_prompt()
        assert "Operating Rules" in result
        assert "Follow the seeded plan" in result
        assert "## Tool Priority" not in result

    def test_prompt_enhancer_no_response_style(self):
        """PromptEnhancer should remain specialized."""
        result = load_agent_instructions("prompt_enhancer")
        assert "Response Style" not in result
        assert "Prompt Enhancer" in result
        assert "AI Agent Capabilities" in result

    def test_variables_substituted_in_resident_only(self):
        """Placeholders in resident content are replaced; extras are not templated.

        Substitution is scoped to identity + base sections only (per the
        hardening pass): runtime-context ``extras`` is never subject to
        variable replacement, so a placeholder there is left verbatim.
        """
        result = load_agent_instructions(
            "aria",
            extras="Value: {{TEST_KEY}}",
            variables={"TEST_KEY": "replaced_value"},
        )
        # extras placeholder is runtime context — left untouched
        assert "{{TEST_KEY}}" in result
        assert "replaced_value" not in result

    def test_unresolved_placeholder_raises(self, tmp_path, monkeypatch):
        """An unresolved resident placeholder must raise, not ship a literal."""
        import aria.agents.instructions as mod

        monkeypatch.setattr(mod, "INSTRUCTIONS_DIR", tmp_path)
        (tmp_path / "unresolved_agent.md").write_text(
            "Hello {{MISSING_KEY}} world", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="Unresolved instruction placeholders"):
            load_agent_instructions("unresolved_agent", base_sections=[])

    def test_resident_placeholder_substituted(self, tmp_path, monkeypatch):
        """A resident placeholder with a matching variable is replaced."""
        import aria.agents.instructions as mod

        monkeypatch.setattr(mod, "INSTRUCTIONS_DIR", tmp_path)
        (tmp_path / "templated_agent.md").write_text(
            "Hello {{NAME}} world", encoding="utf-8"
        )
        result = load_agent_instructions(
            "templated_agent",
            variables={"NAME": "Aria"},
            base_sections=[],
        )
        assert "Hello Aria world" in result
        assert "{{NAME}}" not in result

    def test_unused_variable_key_is_ok(self, tmp_path, monkeypatch):
        """An unused variable key must not trigger the unresolved check."""
        import aria.agents.instructions as mod

        monkeypatch.setattr(mod, "INSTRUCTIONS_DIR", tmp_path)
        (tmp_path / "ok_agent.md").write_text("No placeholders here", encoding="utf-8")
        result = load_agent_instructions(
            "ok_agent",
            variables={"UNUSED": "value"},
            base_sections=[],
        )
        assert "No placeholders here" in result

    def test_base_sections_selective_loading(self):
        """Only requested base sections should be included."""
        result = load_agent_instructions("prompt_enhancer", base_sections=["core"])
        assert "Operating Rules" in result
        assert "## Tools" not in result
        assert "Failure Handling" not in result

    def test_base_sections_default_loads_all(self):
        """Default (None) should load all base sections."""
        result = load_agent_instructions("aria")
        base_dir = Path(__file__).parent.parent / "base"
        for section in ALL_BASE_SECTIONS:
            section_path = base_dir / f"{section}.md"
            if section_path.exists():
                content = section_path.read_text()
                first_heading = next(
                    (line for line in content.splitlines() if line.startswith("## ")),
                    None,
                )
                if first_heading:
                    assert first_heading.lstrip("# ") in result

    def test_base_sections_empty_list(self):
        """Empty list should load no base sections."""
        result = load_agent_instructions("aria", base_sections=[])
        # The base ``## Core Rules`` heading must be absent. (Aria's own
        # prose mentions "Core Rules", so assert the heading, not the substring.)
        assert "## Core Rules" not in result
        assert "Delegation" in result  # agent-specific still loads
