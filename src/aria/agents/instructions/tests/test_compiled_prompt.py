"""Guardrails against system-prompt bloat and rule duplication regressions.

These tests compile each agent's full system prompt the way it would be
assembled at runtime and assert:

- **Budget**: resident (identity + base sections, excluding runtime extras)
  word count stays under an explicit cap (post-cleanup size + 15% headroom).
  Resident-only keeps the guardrail deterministic across machines/CI. Fails
  if bloat returns.
- **Duplication**: no paragraph in an agent's own markdown is near-identical
  to a paragraph in a base section it loads (aria + worker only — the two
  that share base sections). Fails with the offending fragment names.
- **Unresolved placeholders**: no ``{{...}}`` survives in a compiled prompt.
"""

import re
from pathlib import Path

import pytest

from aria.agents.aria import ChatterAgent
from aria.agents.instructions import load_agent_instructions
from aria.agents.prompt_enhancer import PromptEnhancerAgent
from aria.agents.worker import WorkerAgent

INSTRUCTIONS_DIR = Path(__file__).parent.parent
BASE_DIR = INSTRUCTIONS_DIR / "base"

_PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")

# Resident-only (identity + base sections, no runtime extras) word-count
# budgets = post-cleanup baseline + 15% headroom. Measured on resident
# content only so the guardrail tracks markdown bloat, not environment-
# dependent extras (managed binaries / venv table).
ARIA_BUDGET_WORDS = 1545  # resident baseline 1344 (capability map added)
WORKER_BUDGET_WORDS = 615  # resident baseline 534
PROMPT_ENHANCER_BUDGET_WORDS = 584  # resident baseline 507

# A paragraph in an agent md that is >40% token-overlap (Jaccard) with a
# paragraph in a base section it loads counts as duplicated. Baseline
# post-dedup max is ~0.19, so this catches reintroduced near-verbatim rules.
DUPLICATION_JACCARD_THRESHOLD = 0.4

# Per-agent base-section configuration as each agent actually loads it.
# aria passes None (loads all base sections); worker/prompt_enhancer pass
# explicit lists.
_AGENT_RESIDENT_BASE: dict[str, list[str] | None] = {
    "aria": None,
    "worker": ["core", "failure"],
    "prompt_enhancer": [],
}

# Base sections each duplication-scanned agent loads (explicit, for the scan).
_AGENT_BASE_SECTIONS = {
    "aria": ["core", "tools", "failure"],
    "worker": ["core", "failure"],
}


def _word_count(text: str) -> int:
    return len(text.split())


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]


def _norm_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[#*`|>\[\]()\"]", " ", text.lower())
    return set(re.findall(r"[a-z0-9]+", cleaned))


def _max_jaccard(agent_md: str, base_md: str) -> tuple[float, str]:
    """Return (max paragraph Jaccard, description) between two fragments."""
    agent_pars = _paragraphs(agent_md)
    base_pars = _paragraphs(base_md)
    max_j = 0.0
    desc = ""
    for i, ap in enumerate(agent_pars):
        at = _norm_tokens(ap)
        if len(at) < 6:
            continue
        for j, bp in enumerate(base_pars):
            bt = _norm_tokens(bp)
            if len(bt) < 6:
                continue
            jacc = len(at & bt) / len(at | bt)
            if jacc > max_j:
                max_j = jacc
                desc = f"agent paragraph {i} vs base paragraph {j} (Jaccard={jacc:.3f})"
    return max_j, desc


@pytest.fixture(
    params=[
        ("aria", ChatterAgent, ARIA_BUDGET_WORDS),
        ("worker", WorkerAgent, WORKER_BUDGET_WORDS),
        ("prompt_enhancer", PromptEnhancerAgent, PROMPT_ENHANCER_BUDGET_WORDS),
    ],
    ids=["aria", "worker", "prompt_enhancer"],
)
def agent_case(request):
    name, cls, budget = request.param
    full_prompt = cls.get_instructions()
    return name, cls, budget, full_prompt


class TestPromptBudget:
    """Resident (identity + base) word count must stay under budget.

    Measured on resident content only — runtime extras (managed binaries,
    venv table) are environment-dependent and excluded so the guardrail is
    deterministic across machines/CI.
    """

    def test_resident_under_budget(self, agent_case):
        name, _cls, budget, _full_prompt = agent_case
        resident = load_agent_instructions(
            name, extras=None, base_sections=_AGENT_RESIDENT_BASE[name]
        )
        words = _word_count(resident)
        assert words <= budget, (
            f"{name} resident prompt grew to {words} words (budget {budget}). "
            f"Trim it or raise the budget with justification."
        )


class TestUnresolvedPlaceholders:
    """No ``{{...}}`` may survive in a compiled prompt."""

    def test_no_unresolved_placeholders(self, agent_case):
        name, _cls, _budget, full_prompt = agent_case
        matches = _PLACEHOLDER_RE.findall(full_prompt)
        assert not matches, f"{name} prompt has unresolved placeholders: {matches}"


class TestAriaBehaviorContracts:
    """Prompt reduction must preserve quality-sensitive operating behavior."""

    @pytest.fixture
    def prompt(self) -> str:
        return load_agent_instructions("aria")

    def test_discovers_ax_arguments_before_guessing(self, prompt: str):
        assert 'family="help", command="lookup"' in prompt
        assert "before guessing" in prompt

    def test_multi_file_work_does_not_force_delegation(self, prompt: str):
        assert "outline a brief plan first" in prompt
        assert "delegate only when the work also meets" in prompt

    @pytest.mark.parametrize(
        "contract",
        [
            "Ask for explicit approval",
            "Cite only what you fetched",
            "Retry transient failures once",
            "Stop at the first blocker or after 5 unproductive calls",
            "ordered verifiable `steps` ending in a check",
        ],
    )
    def test_retains_essential_contract(self, prompt: str, contract: str):
        assert contract in prompt


class TestNoDuplicatedRules:
    """Agent markdown must not duplicate base-section rules (aria + worker)."""

    @pytest.mark.parametrize("agent_name", ["aria", "worker"])
    def test_no_high_overlap_with_base_sections(self, agent_name):
        agent_md = (INSTRUCTIONS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
        offenders = []
        for section in _AGENT_BASE_SECTIONS[agent_name]:
            base_md = (BASE_DIR / f"{section}.md").read_text(encoding="utf-8")
            max_j, desc = _max_jaccard(agent_md, base_md)
            if max_j >= DUPLICATION_JACCARD_THRESHOLD:
                offenders.append(f"{section}.md: {desc}")
        assert not offenders, (
            f"{agent_name}.md duplicates base-section content "
            f"(Jaccard >= {DUPLICATION_JACCARD_THRESHOLD}): {offenders}"
        )

    def test_prompt_enhancer_loads_no_base_sections(self):
        """prompt_enhancer loads base_sections=[] — duplication scan N/A."""
        from aria.agents.instructions import load_agent_instructions

        result = load_agent_instructions("prompt_enhancer", base_sections=[])
        assert "## Core Rules" not in result
        assert "## Tool Priority" not in result
        assert "## Failure Handling" not in result
