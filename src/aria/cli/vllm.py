"""vLLM engine management commands for the Aria CLI.

vLLM is an **external tool**: Aria installs it into an isolated venv
(``~/.aria/venvs/vllm``) and launches it as an OpenAI-compatible
server over HTTP.  Aria's own environment never imports vLLM.

Commands:
    install: Build the isolated vLLM venv and install the pinned wheel
    update: Recreate the isolated venv at a newer version
    uninstall: Remove the isolated venv (+ ``--legacy`` to purge an
        in-Aria-env copy from before the detach)
    status: Check installation status, version, and venv path
    info: Show vLLM configuration details
    start: Start the vLLM inference server
    stop: Stop the vLLM inference server
    restart: Stop then start the vLLM server only

Example:
    ```bash
    # Install vLLM with auto-detected hardware target
    aria vllm install

    # Install a specific pinned release
    aria vllm install --version 0.24.0

    # Update to the latest PyPI release (recreates the venv)
    aria vllm update

    # Check installation status
    aria vllm status

    # Start the vLLM server
    aria vllm start

    # Restart only the vLLM server (no web UI / model-download side effects)
    aria vllm restart

    # Stop the vLLM server
    aria vllm stop

    # Remove the isolated venv
    aria vllm uninstall

    # Remove a legacy in-Aria-env copy
    aria vllm uninstall --legacy
    ```
"""

import typer
from rich.console import Console
from rich.table import Table

from aria.scripts.vllm import get_vllm_version, is_vllm_installed

app = typer.Typer(
    name="vllm",
    help="vLLM inference engine management commands.",
)

console = Console()
error_console = Console(stderr=True, style="bold red")


def _print_legacy_notice() -> None:
    """Warn if a vLLM copy lingers in Aria's own environment."""
    from aria.scripts.vllm import detect_legacy_vllm

    legacy = detect_legacy_vllm()
    if legacy:
        console.print(
            f"[yellow]Note:[/yellow] vLLM {legacy} found in Aria's own "
            "environment; it is now ignored. Remove it with "
            "`aria vllm uninstall --legacy`."
        )


def _remote_notice(action: str) -> bool:
    """Print the externally-managed notice and return True when in remote mode."""
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        console.print(
            f"vLLM is externally managed (ARIA_VLLM_REMOTE=true) — nothing to {action}."
        )
        return True
    return False


@app.command("install")
def install_command(
    version: str | None = typer.Option(
        None, "--version", help="Override the pinned vLLM release version."
    ),
):
    """Build the isolated vLLM venv and install the pinned wheel.

    Automatically detects CUDA, ROCm, or CPU, builds the venv at
    ``~/.aria/venvs/vllm``, installs the prebuilt PyPI wheel into it,
    and creates the ``~/.aria/bin/vllm`` shim.

    Example:
        ```bash
        aria vllm install
        aria vllm install --version 0.24.0
        ```
    """
    from aria.scripts.vllm import install_vllm

    try:
        install_vllm(version=version)
    except Exception as e:
        error_console.print(f"[red]✗[/red] Installation failed: {e}")
        raise typer.Exit(1)
    _print_legacy_notice()


def _resolve_update_target(version: str | None, latest: bool) -> str:
    from aria.config.api import Vllm as VllmConfig
    from aria.scripts.vllm import get_latest_vllm_version

    if version:
        return version
    if latest:
        latest_version = get_latest_vllm_version()
        if latest_version:
            return latest_version
    return VllmConfig.version


def _was_vllm_running() -> bool:
    from aria.server.vllm import VllmServerManager

    mgr = VllmServerManager()
    return bool(mgr._pids) or bool(VllmServerManager._find_orphan_pids())


def _stop_and_update(target: str, was_running: bool) -> None:
    from aria.scripts.vllm import update_vllm
    from aria.server.vllm import VllmServerManager

    if was_running:
        console.print("Stopping vLLM before update...")
        VllmServerManager().stop_all()
    update_vllm(version=target)


def _report_update_result(target: str, was_running: bool) -> None:
    from aria.server.vllm import VllmServerManager

    if was_running:
        VllmServerManager().start_all()
        console.print(f"[green]✓[/green] vLLM updated to {target} and restarted.")
    else:
        console.print(
            f"[green]✓[/green] vLLM updated to {target}. Run: aria vllm start"
        )


@app.command("update")
def update_command(
    version: str | None = typer.Option(
        None, "--version", help="Explicit target version."
    ),
    latest: bool = typer.Option(
        True, "--latest/--no-latest", help="Query PyPI for the newest release."
    ),
    force: bool = typer.Option(
        False, "--force", help="Reinstall even when already at the target version."
    ),
):
    """Update the isolated vLLM by recreating its venv.

    Flow:
        1. Resolve target version (explicit, or latest via PyPI, falling
           back to the pinned ``Vllm.version`` when offline).
        2. Skip with "already up to date" if equal and ``--force`` not set.
        3. Stop a running server (remembering whether it was running).
        4. Recreate the venv at the target version.
        5. Restart only if it had been running.

    In remote mode, refuses without touching the venv.
    """
    if _remote_notice("update"):
        return

    from aria.scripts.vllm import get_vllm_version

    target = _resolve_update_target(version, latest)
    current = get_vllm_version()
    if current == target and not force:
        console.print(f"vLLM is already up to date ({current}).")
        return

    was_running = _was_vllm_running()
    try:
        _stop_and_update(target, was_running)
    except Exception as e:
        error_console.print(f"[red]✗[/red] Update failed: {e}")
        raise typer.Exit(1)

    _report_update_result(target, was_running)


@app.command("uninstall")
def uninstall_command(
    legacy: bool = typer.Option(
        False,
        "--legacy",
        help="Purge a vLLM copy in Aria's own .venv (from before the detach) "
        "instead of the isolated venv.",
    ),
):
    """Remove the isolated vLLM venv (or a legacy in-Aria-env copy).

    Example:
        ```bash
        aria vllm uninstall            # remove ~/.aria/venvs/vllm + shim
        aria vllm uninstall --legacy   # remove vLLM from Aria's own .venv
        ```
    """
    if _remote_notice("uninstall"):
        return

    from aria.scripts.vllm import uninstall_legacy_vllm, uninstall_vllm

    if legacy:
        uninstall_legacy_vllm()
        console.print("[green]✓[/green] Removed vLLM from Aria's own environment.")
        return

    try:
        uninstall_vllm()
    except Exception as e:
        error_console.print(f"[red]✗[/red] Uninstall failed: {e}")
        raise typer.Exit(1)
    console.print("[green]✓[/green] Removed the isolated vLLM venv and shim.")


@app.command("status")
def check_status():
    """Check vLLM installation status, version, and venv path.

    Example:
        ```bash
        aria vllm status
        ```
    """
    from aria.config.api import Vllm as VllmConfig

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan", width=20)
    table.add_column("Value", style="green")

    if is_vllm_installed():
        version = get_vllm_version()
        table.add_row("vLLM", "[green]✓ Installed[/green]")
        table.add_row("Version", version)
        table.add_row("Venv", str(VllmConfig.get_venv_path()))
    else:
        table.add_row("vLLM", "[red]✗ Not installed[/red]")
        table.add_row("Install", "Run: aria vllm install")

    console.print(table)
    _print_legacy_notice()


def _or_dim(value, dim_label: str) -> str:
    return str(value) if value else f"[dim]{dim_label}[/dim]"


def _on_or_off(condition: bool) -> str:
    return "[green]\u2713[/green]" if condition else "[dim]off[/dim]"


def _engine_table() -> Table:
    from aria.config.api import Vllm as VllmConfig

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan", width=28)
    table.add_column("Value", style="green")

    table.add_row("Chat Context Size", str(VllmConfig.chat_context_size))
    table.add_row("Max Output Tokens", str(VllmConfig.max_tokens))
    table.add_row(
        "GPU Memory Utilization",
        _or_dim(VllmConfig.gpu_memory_utilization, "auto"),
    )
    table.add_row("Quantization", _or_dim(VllmConfig.quantization, "none"))
    table.add_row("Dtype", VllmConfig.dtype)
    table.add_row("KV Cache Dtype", VllmConfig.kv_cache_dtype)
    table.add_row("Tensor Parallel Size", str(VllmConfig.tensor_parallel_size))
    table.add_row("Data Parallel Size", str(VllmConfig.data_parallel_size))
    table.add_row("Expert Parallel", _on_or_off(VllmConfig.expert_parallel))
    table.add_row("Prefix Caching", _on_or_off(VllmConfig.prefix_caching))
    table.add_row("Vision Enabled", _on_or_off(VllmConfig.vision_enabled))
    table.add_row("Tool Call Parser", _or_dim(VllmConfig.tool_call_parser, "none"))
    table.add_row("Reasoning Parser", _or_dim(VllmConfig.reasoning_parser, "none"))
    table.add_row("Chat Template", _or_dim(VllmConfig.chat_template_file, "default"))
    table.add_row(
        "Chat Template Kwargs", _or_dim(VllmConfig.chat_template_kwargs, "none")
    )
    return table


def _offload_table() -> Table:
    from aria.config.api import Vllm as VllmConfig

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan", width=28)
    table.add_column("Value", style="green")
    table.add_row("Offload Mode", VllmConfig.kv_offload_mode)
    table.add_row(
        "Offload Size (GiB)",
        _or_dim(VllmConfig.kv_offloading_size_gb, "auto"),
    )
    table.add_row("Offload Backend", VllmConfig.kv_offloading_backend)
    return table


def _sampling_table() -> Table:
    from aria.config.api import Vllm as VllmConfig

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan", width=28)
    table.add_column("Value", style="green")
    table.add_row("Temperature", str(VllmConfig.temperature))
    table.add_row("Top P", str(VllmConfig.top_p))
    table.add_row("Top K", str(VllmConfig.top_k))
    table.add_row("Min P", str(VllmConfig.min_p))
    table.add_row("Repetition Penalty", str(VllmConfig.repetition_penalty))
    table.add_row("Seed", str(VllmConfig.seed))
    return table


def _print_info_section(title: str, table: Table) -> None:
    console.print(f"\n[bold]{title}[/bold]\n")
    console.print(table)


@app.command("info")
def info_command():
    """Show vLLM configuration details.

    Displays the current vLLM engine configuration from .env,
    organized by category.

    Example:
        ```bash
        aria vllm info
        ```
    """
    _print_info_section("Engine", _engine_table())
    _print_info_section("KV Cache Offloading", _offload_table())
    _print_info_section("Sampling", _sampling_table())


@app.command("start")
def start_command():
    """Start the vLLM inference server.

    Ensures required directories exist, then starts the vLLM server
    and waits for it to become healthy.

    Example:
        ```bash
        aria vllm start
        ```
    """
    if _remote_notice("start"):
        return

    from urllib.error import URLError
    from urllib.request import urlopen

    from aria.config.folders import Debug as DebugConfig
    from aria.config.models import Chat
    from aria.server.vllm import VllmServerManager

    # Ensure log directory exists
    DebugConfig.path.mkdir(parents=True, exist_ok=True)

    # Check if already running
    port = Chat.get_port()
    try:
        with urlopen(f"http://localhost:{port}/health", timeout=3) as resp:
            if resp.status == 200:
                console.print(
                    f"[yellow]vLLM server is already running[/yellow] (port {port})"
                )
                return
    except (URLError, OSError):
        pass

    console.print("[dim]Starting vLLM server...[/dim]")
    try:
        vllm = VllmServerManager()
        vllm.start_all()
        console.print(f"[green]✓[/green] vLLM server started on port {port}")
    except Exception as e:
        error_console.print(f"[red]✗[/red] Failed to start vLLM: {e}")
        raise typer.Exit(1)


@app.command("stop")
def stop_command():
    """Stop the vLLM inference server.

    Gracefully stops all running vLLM server processes, including
    orphaned processes not tracked by the PID file.

    Example:
        ```bash
        aria vllm stop
        ```
    """
    if _remote_notice("stop"):
        return

    from aria.server.vllm import VllmServerManager

    vllm = VllmServerManager()

    if not vllm._pids:
        # Double-check for orphaned processes
        orphans = VllmServerManager._find_orphan_pids()
        if not orphans:
            console.print("[yellow]vLLM server is not running[/yellow]")
            return

    console.print("[dim]Stopping vLLM server...[/dim]")
    try:
        vllm.stop_all()
        console.print("[green]✓[/green] vLLM server stopped")
    except Exception as e:
        error_console.print(f"[red]✗[/red] Failed to stop vLLM: {e}")
        raise typer.Exit(1)


@app.command("restart")
def restart_command():
    """Restart only the vLLM server (stop then start).

    Equivalent to ``aria server start --force-restart-vllm`` but scoped
    to the vLLM server only — no web UI / preflight / model-download
    side effects.  Useful for reloading a model with new config (e.g.
    changed ``CHAT_CONTEXT_SIZE``) without bouncing the whole web stack.

    Example:
        ```bash
        aria vllm restart
        ```
    """
    if _remote_notice("restart"):
        return

    from aria.server.vllm import VllmServerManager

    try:
        mgr = VllmServerManager()
        mgr.stop_all()  # graceful, includes orphan scan
        mgr.start_all()  # waits for /health internally
        console.print("[green]✓[/green] vLLM restarted.")
    except Exception as e:
        error_console.print(f"[red]✗[/red] Restart failed: {e}")
        raise typer.Exit(1)
