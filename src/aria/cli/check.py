"""Check CLI commands for Aria.

Provides subcommands under ``aria check``:

- ``aria check preflight`` — verify all prerequisites for running the web UI
- ``aria check instructions`` — display the full system prompt for each agent

Example:
    ```bash
    aria check preflight
    aria check instructions
    aria check instructions --agent aria
    aria check instructions --raw
    ```
"""

import logging

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Suppress noisy debug logs from markdown_it and similar libraries
logging.getLogger("markdown_it").setLevel(logging.WARNING)
logging.getLogger("markdownify").setLevel(logging.WARNING)

app = typer.Typer(
    name="check",
    help="Verify system prerequisites and view agent instructions.",
    rich_markup_mode="rich",
    add_completion=False,
)

console = Console()
error_console = Console(stderr=True, style="bold red")

# ── Category display configuration ──────────────────────────────────────────

CATEGORY_CONFIG = {
    "environment": {"icon": "📦", "label": "Environment Variables"},
    "storage": {"icon": "📁", "label": "Data & Storage"},
    "binaries": {"icon": "⚙️ ", "label": "Binaries"},
    "models": {"icon": "🧠", "label": "Models"},
    "hardware": {"icon": "🖥️ ", "label": "Hardware"},
    "connectivity": {"icon": "🌐", "label": "Connectivity"},
    "tools": {"icon": "🔧", "label": "Tools"},
}


# ── Preflight helpers ────────────────────────────────────────────────────────


def _print_check_header():
    """Print the check command header panel."""
    console.print()
    console.print(
        Panel(
            "[bold]🔍 ARIA SYSTEM CHECK[/bold]",
            border_style="cyan",
            expand=False,
            padding=(0, 2),
        )
    )
    console.print()


def _print_category(category: str, checks: list) -> tuple[int, int]:
    """Print a category and its checks.

    Returns:
        Tuple of (passed_count, failed_count) for this category.
    """
    config = CATEGORY_CONFIG.get(category, {"icon": "•", "label": category.title()})
    passed = sum(1 for c in checks if c.passed)
    failed = len(checks) - passed

    # Category header
    if failed == 0:
        status = f"[green]{passed}/{len(checks)}[/green]"
    else:
        status = f"[red]{passed}/{len(checks)}[/red]"
    console.print(f"{config['icon']} {config['label']} {status}")

    # Individual checks
    for check in checks:
        if check.passed:
            if check.warning:
                details = (
                    f" [yellow]({check.details})[/yellow]" if check.details else ""
                )
                console.print(f"   [yellow]⚠[/yellow] {check.name}{details}")
            else:
                details = f" [dim]({check.details})[/dim]" if check.details else ""
                console.print(f"   [green]✓[/green] {check.name}{details}")
        else:
            console.print(f"   [red]✗[/red] {check.name} - [red]{check.error}[/red]")
            if check.hint:
                console.print(f"      [dim]→ {check.hint}[/dim]")

    console.print()
    return passed, failed


def _print_summary_panel(total_passed: int, total_failed: int, hints: list):
    """Print the final summary panel."""
    total = total_passed + total_failed

    if total_failed == 0:
        content = f"[green]✅ All {total} checks passed - System ready![/green]"
        style = "green"
    else:
        plural = "s" if total_failed > 1 else ""
        lines = [
            (
                f"[red]❌ {total_failed} check{plural} failed - "
                "Fix issues before starting[/red]"
            ),
        ]
        if hints:
            lines.append("")
            lines.append("[bold]Quick fixes:[/bold]")
            for i, hint in enumerate(hints[:3], 1):
                lines.append(f"  {i}. {hint}")
        content = "\n".join(lines)
        style = "red"

    console.print(
        Panel(
            content,
            border_style=style,
            expand=False,
            padding=(0, 1),
        )
    )


# ── Preflight subcommand ────────────────────────────────────────────────────


@app.command("preflight")
def preflight():
    """Verify all prerequisites for running the Aria web UI.

    Performs comprehensive preflight checks:
    1. Required environment variables are set
    2. Data folder exists
    3. vLLM is installed
    4. All required models are configured and downloaded
    5. Token limit is within context bounds
    6. Memory requirements fit available hardware
    7. LLM server connectivity (informational)
    8. Knowledge database access
    9. Tool loading
    10. Database connectivity and write permissions

    Example:
        ```bash
        aria check preflight
        ```
    """
    from sqlalchemy import text

    from aria.cli import get_db_session
    from aria.preflight import CheckResult, run_preflight_checks

    _print_check_header()

    result = run_preflight_checks()
    grouped = result.group_by_category()

    # Database check (add to storage category)
    db_check = CheckResult(name="Database", passed=True, category="storage")
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
            session.execute(text("CREATE TABLE IF NOT EXISTS health (id int)"))
            session.execute(text("DROP TABLE health"))
            db_check.details = "connection healthy (writable)"
    except Exception:
        db_check.passed = False
        db_check.error = "connection failed"
        db_check.hint = "Check that aria.db exists and is writable"

    # Add database check to storage category
    if "storage" not in grouped:
        grouped["storage"] = []
    grouped["storage"].append(db_check)

    # Track totals
    total_passed = 0
    total_failed = 0
    all_hints = []

    # Print each category in defined order
    for category in CATEGORY_CONFIG.keys():
        if category in grouped:
            passed, failed = _print_category(category, grouped[category])
            total_passed += passed
            total_failed += failed
            for check in grouped[category]:
                if not check.passed and check.hint:
                    all_hints.append(check.hint)

    # Print summary
    _print_summary_panel(total_passed, total_failed, all_hints)

    if total_failed > 0:
        raise typer.Exit(1)


# ── Instructions subcommand ─────────────────────────────────────────────────

# Agent registry: name → (label, class)
# Lazy-loaded to avoid import-time side effects.
_AGENT_REGISTRY: dict[str, tuple[str, type]] = {}


def _get_agent_registry() -> dict[str, tuple[str, type]]:
    """Return the agent registry, loading classes on first call."""
    if not _AGENT_REGISTRY:
        from aria.agents.aria import ChatterAgent
        from aria.agents.prompt_enhancer import PromptEnhancerAgent
        from aria.agents.worker import WorkerAgent

        _AGENT_REGISTRY.update(
            {
                "aria": ("Aria (Main Agent)", ChatterAgent),
                "worker": ("Worker (Background Agent)", WorkerAgent),
                "prompt_enhancer": ("Prompt Enhancer", PromptEnhancerAgent),
            }
        )
    return _AGENT_REGISTRY


@app.command("instructions")
def instructions(
    agent: str | None = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent name to display. Omit to show all agents.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw markdown with no Rich formatting (useful for piping).",
    ),
):
    """Display the full system prompt / instructions for each agent.

    Each agent class exposes a ``get_instructions()`` method that returns
    the exact system prompt it would receive at runtime, including all
    base sections, agent-specific markdown, and runtime extras.

    Example:
        ```bash
        # Show all agents
        aria check instructions

        # Show specific agent
        aria check instructions --agent aria

        # Raw markdown for piping
        aria check instructions --raw > instructions.md
        ```
    """
    registry = _get_agent_registry()

    # Resolve which agents to display
    if agent:
        agent_lower = agent.lower().strip()
        if agent_lower not in registry:
            error_console.print(
                f"Unknown agent '{agent}'. Available: {', '.join(registry.keys())}"
            )
            raise typer.Exit(1)
        agents_to_show = {agent_lower: registry[agent_lower]}
    else:
        agents_to_show = registry

    for name, (label, agent_cls) in agents_to_show.items():
        full_prompt = agent_cls.get_instructions()

        if raw:
            # Bare markdown — easy to pipe or redirect
            typer.echo(full_prompt)
            if len(agents_to_show) > 1:
                typer.echo("\n---\n")
        else:
            # Rich-rendered panel
            console.print()
            console.print(
                Panel(
                    Markdown(full_prompt),
                    title=f"[bold]{label}[/bold]",
                    title_align="left",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )

    if not raw:
        console.print()


# ── Extras subcommand ───────────────────────────────────────────────────────


@app.command("extras")
def extras(
    filter_term: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter binaries by substring match.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw markdown with no Rich formatting (useful for piping).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output structured JSON (easy for agents to parse).",
    ),
):
    """Display extra CLI tools available in the virtual environment.

    Scans the active venv's bin directory for user-facing CLI binaries
    that agents can call via shell.

    Example:
        ```bash
        # Show all extras
        ax check extras

        # Filter by term
        ax check extras --filter http

        # Raw markdown for piping
        ax check extras --raw

        # JSON output for agents
        ax check extras --json
        ```
    """
    import json

    from aria.cli.extras import get_venv_extras, get_venv_extras_json

    if json_output:
        result = get_venv_extras_json(filter_term=filter_term)
        console.print(json.dumps(result, indent=2))
    else:
        result = get_venv_extras(filter_term=filter_term)

        if raw:
            console.print(result)
        else:
            console.print()
            console.print(
                Panel(
                    Markdown(result),
                    title="[bold]🔧 Extra Binaries Available[/bold]",
                    title_align="left",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )
            console.print()
