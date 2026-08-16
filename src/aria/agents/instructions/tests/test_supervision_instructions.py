"""Instruction and plan-section contract tests."""

from pathlib import Path

from aria.cli.worker._runner import PLAN_SECTION_TEMPLATE, _build_prompt

INST = Path(__file__).resolve().parents[1]
REF = INST / "reference" / "ax_commands.md"


def test_aria_md_spawn_example_includes_steps():
    text = (INST / "aria.md").read_text()
    assert '"steps":' in text


def test_worker_md_no_longer_says_create_plan():
    text = (INST / "worker.md").read_text()
    assert "Create concrete steps" not in text
    assert "Create before any work" not in text


def test_worker_md_uses_correct_memory_and_spawn_boundary():
    text = (INST / "worker.md").read_text()
    assert "Persistent memory is unavailable" in text
    assert "Do not spawn workers" in text


def test_aria_md_supports_rich_markdown():
    text = (INST / "aria.md").read_text()
    assert "Use Markdown deliberately" in text
    assert "Lead with the conclusion" in text


def test_ax_reference_worker_spawn_lists_steps_required():
    text = REF.read_text()
    start = text.index("## worker")
    section = text[start : text.index("## mcp")]
    spawn = next(line for line in section.splitlines() if line.startswith("| `spawn`"))
    required = spawn.split("|")[2]
    assert "steps" in required


def test_plan_section_template_renders():
    rendered = PLAN_SECTION_TEMPLATE.format(plan_id="P", agent_id="W")
    assert "P" in rendered and "W" in rendered
    assert 'plan(action="get"' in rendered
    from types import SimpleNamespace

    args = SimpleNamespace(
        prompt="do it",
        reason=None,
        expected=None,
        instructions=None,
        plan_id="P",
        worker_id="W",
    )
    assert (
        _build_prompt(args)
        == "<delegated_task>\ndo it\n</delegated_task>\n\n" + rendered
    )
