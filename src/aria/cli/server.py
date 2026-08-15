"""Server CLI commands for the Aria application.

This module provides CLI commands to manage the Aria webserver:
- run: Run the server in foreground (blocking)
- start: Start the server in background
- stop: Stop the server
- status: Show server status (web_ui and vLLM servers)

vLLM servers are managed internally by the web_ui via Chainlit lifecycle hooks.

Example:
    ```bash
    # Run in foreground (Ctrl+C to stop)
    aria server run

    # Start in background
    aria server start

    # Check status
    aria server status

    # Stop server
    aria server stop
    ```
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

import typer
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aria.config.folders import Debug as DebugConfig
from aria.preflight import run_preflight_checks
from aria.server import ServerManager
from aria.server.lifecycle import (
    ensure_endpoint_reachable,
    is_vllm_healthy,
    stop_server,
    wait_for_web_health,
)

app = typer.Typer(
    name="server",
    help="Manage the Aria webserver",
)
console = Console()
error_console = Console(stderr=True, style="bold red")

# Health check settings
HEALTH_CHECK_TIMEOUT = 180  # seconds (vLLM model loading can take 30s+)


def _print_startup_banner(host: str, port: int, background: bool = False) -> None:
    mode = "Background" if background else "Foreground"
    action = "Starting Aria Web UI"
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{action}[/bold cyan]\n"
            f"[white]{host}:{port}[/white]"
            f" • [dim]{mode} mode[/dim]",
            border_style="cyan",
            expand=False,
            padding=(0, 2),
        )
    )


def _print_startup_failure(message: str) -> None:
    from aria.scripts.vllm import is_vllm_installed

    vllm_line = ""
    if is_vllm_installed():
        vllm_line = (
            f"\n[dim]vLLM log:[/dim] {DebugConfig.logs_path.parent / 'vllm.log'}"
        )

    error_console.print()
    error_console.print(
        Panel(
            f"[bold red]Startup failed[/bold red]\n{message}\n\n"
            f"[dim]See logs:[/dim] {DebugConfig.logs_path}{vllm_line}",
            border_style="red",
            expand=False,
            padding=(0, 2),
        )
    )


def _get_captured_startup_error() -> str | None:
    return ServerManager.get_startup_error()


def _print_vllm_startup_failure(exc: Exception) -> None:
    _print_startup_failure(
        _get_captured_startup_error() or f"Failed to start vLLM: {exc}"
    )


def _get_startup_failure_message(exc: Exception | None = None) -> str:
    captured = _get_captured_startup_error()
    if captured:
        return captured
    if exc is not None:
        return str(exc)
    return "Aria Web UI failed to start. Check the log files for details."


def _print_preflight_result(result) -> bool:
    """Print preflight results as a clean bordered panel and return True if all pass."""
    grouped = result.group_by_category()

    category_config = {
        "hardware": "Hardware",
        "environment": "Environment",
        "models": "Models",
        "binaries": "Binaries",
        "storage": "Storage",
        "connectivity": "Connectivity",
        "tools": "Tools",
    }

    lines: list[str] = []

    for category in category_config:
        if category not in grouped:
            continue
        checks = grouped[category]
        passed = sum(1 for c in checks if c.passed)
        total = len(checks)
        label = category_config[category]
        all_ok = passed == total

        badge = (
            f"[green]{passed}/{total}[/green]"
            if all_ok
            else f"[red]{passed}/{total}[/red]"
        )
        lines.append(f"[bold]{label}[/bold]  {badge}")

        for check in checks:
            if check.passed:
                tag = "[green]✓[/green]"
                text = check.name
                if check.details:
                    text += f"  [dim]{check.details}[/dim]"
            else:
                tag = "[red]✗[/red]"
                text = f"{check.name}  [red]{check.error}[/red]"
                if check.hint:
                    text += f"  [dim]→ {check.hint}[/dim]"
            lines.append(f"  {tag}  {text}")
        lines.append("")

    if result.passed:
        title = "[bold green]✓ Preflight passed[/bold green]"
        border = "green"
    else:
        title = "[bold red]✗ Preflight failed[/bold red]"
        border = "red"

    # Strip the trailing empty line so the panel doesn't have a gap at the bottom.
    if lines and lines[-1] == "":
        lines.pop()

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title=title,
            border_style=border,
            box=ROUNDED,
            expand=False,
            padding=(0, 2),
        )
    )
    console.print()
    return result.passed


def _wait_for_health(
    host: str,
    port: int,
    timeout: float,
    *,
    process_alive: Callable[[], bool] | None = None,
) -> bool:
    """Wait for the web UI to become healthy (delegates to shared lifecycle)."""
    return wait_for_web_health(host, port, timeout, process_alive=process_alive)


@app.command("run")
def server_run():
    """Run the Aria webserver in foreground (blocking).

    vLLM server processes are started automatically by the web_ui.
    Press Ctrl+C to stop.
    """
    _ensure_lightpanda_installed()
    _ensure_models_downloaded()

    # Run preflight checks
    result = run_preflight_checks()
    if not _print_preflight_result(result):
        raise typer.Exit(1)

    _ensure_endpoint_reachable()

    manager = ServerManager()
    _print_startup_banner(manager.host, manager.port)
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    try:
        manager.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")
    except RuntimeError as e:
        _print_startup_failure(_get_startup_failure_message(e))
        raise typer.Exit(1)
    except Exception as e:
        _print_startup_failure(_get_startup_failure_message(e))
        raise typer.Exit(1)

    post_run_error = _get_captured_startup_error()
    if post_run_error:
        _print_startup_failure(post_run_error)
        raise typer.Exit(1)


def _is_vllm_healthy() -> bool:
    """Check if the vLLM chat server is responding to health checks."""
    return is_vllm_healthy()


def _ensure_lightpanda_installed() -> None:
    """Download Lightpanda automatically if it is missing."""
    from aria.config.api import Lightpanda

    if Lightpanda.is_available():
        return

    from aria.scripts.lightpanda import download_lightpanda

    console.print("[dim]Lightpanda not installed — downloading...[/dim]")
    try:
        binary = download_lightpanda(
            bin_dir=Lightpanda.get_bin_path(), version=Lightpanda.version
        )
    except Exception as e:
        error_console.print(f"[red]Failed to install Lightpanda: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Lightpanda installed at {binary}")


def _download_model(alias: str, raw_value: str, path: Path, max_retries: int) -> None:
    from huggingface_hub import snapshot_download
    from rich.status import Status

    from aria.config.huggingface import HuggingFace

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        label = (
            f"Downloading {alias} model ({raw_value})"
            if attempt == 1
            else f"Retrying {alias} model download (attempt {attempt}/{max_retries})"
        )
        try:
            with Status(f"[dim]{label}…[/dim]", console=console):
                snapshot_download(
                    repo_id=raw_value,
                    local_dir=str(path),
                    token=HuggingFace.token,
                    ignore_patterns=["onnx/*", "openvino/*", "openvino_model.*"],
                )
            console.print(f"[green]✓[/green] {alias} model ready at {path}")
            return
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                console.print(
                    f"[yellow]⚠[/yellow] {alias} model download failed "
                    f"(attempt {attempt}/{max_retries}): {e}"
                )

    error_console.print(
        f"[red]Failed to download {alias} model after "
        f"{max_retries} attempts: {last_error}[/red]"
    )
    raise typer.Exit(1)


def _should_auto_download(raw_value: str) -> bool:
    from pathlib import Path

    if not raw_value:
        return False
    return not Path(raw_value).is_absolute()


def _ensure_models_downloaded() -> None:
    """Auto-download models from HuggingFace if they are missing.

    Checks each configured model (chat, embeddings). If the model
    directory does not exist locally and the env var contains a
    HuggingFace repo ID (not an absolute path), downloads the
    snapshot automatically with a progress indicator and retry logic.
    """
    from os import getenv
    from pathlib import Path

    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat, Embeddings

    models_to_check = [
        ("chat", "CHAT_MODEL_PATH", Chat),
        ("embeddings", "EMBED_MODEL_PATH", Embeddings),
    ]

    if VllmConfig.remote:
        models_to_check = [m for m in models_to_check if m[0] != "chat"]

    for alias, env_var, config_cls in models_to_check:
        model_path = config_cls.model_path
        if not model_path:
            continue

        path = Path(model_path)
        if path.exists() and path.is_dir():
            continue

        raw_value = getenv(env_var, "")
        if not _should_auto_download(raw_value):
            continue

        _download_model(alias, raw_value, path, max_retries=3)


def _ensure_endpoint_reachable() -> None:
    """Verify the OpenAI-compatible endpoint is reachable before serving.

    Delegates to the shared lifecycle: remote mode validates the
    configured endpoint (fail-fast); local mode requires CUDA, starts
    vLLM if unhealthy, and waits for health.
    """
    result = ensure_endpoint_reachable(
        progress=lambda m: console.print(f"[dim]{m}[/dim]")
    )
    if result.ok:
        console.print("[green]✓[/green] OpenAI endpoint ready")
        return
    error_console.print(f"[red]✗[/red] {result.error}")
    raise typer.Exit(1)


def _ensure_vllm_running() -> None:
    """Start vLLM servers if they are not already running.

    This is a safety net for two scenarios:
    1. The web UI is already running but vLLM crashed or was never started.
    2. The web UI just started but its lifecycle hook failed to start vLLM.

    In remote mode, just verifies the remote endpoint is reachable.
    """
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        if _is_vllm_healthy():
            console.print("[green]✓[/green] Remote vLLM endpoint reachable")
        else:
            from aria.config.models import Chat

            error_console.print(
                f"[red]✗[/red] Remote vLLM endpoint not reachable: {Chat.api_url}"
            )
            raise typer.Exit(1)
        return

    if _is_vllm_healthy():
        console.print("[green]✓[/green] vLLM servers running")
        return

    from aria.server.vllm import VllmServerManager

    console.print("[dim]vLLM not running — starting...[/dim]")
    try:
        vllm = VllmServerManager()
        vllm.start_all()
        console.print("[green]✓[/green] vLLM servers started")
    except Exception as e:
        _print_vllm_startup_failure(e)
        raise typer.Exit(1)


@app.command("start")
def server_start(
    force_restart_vllm: bool = typer.Option(
        False,
        "--force-restart-vllm",
        help="Stop any running vLLM servers before starting the web UI.",
    ),
):
    """Start the Aria webserver in background.

    vLLM server processes are started automatically by the web_ui.
    """
    _ensure_lightpanda_installed()
    _ensure_models_downloaded()

    # Run preflight checks
    result = run_preflight_checks()
    if not _print_preflight_result(result):
        raise typer.Exit(1)

    # Stop vLLM first if requested (before endpoint validation)
    if force_restart_vllm:
        from aria.server.vllm import VllmServerManager

        vllm = VllmServerManager()
        console.print("[dim]Stopping existing vLLM servers...[/dim]")
        vllm.stop_all()

    _ensure_endpoint_reachable()

    manager = ServerManager()
    if manager.is_running():
        console.print(f"[yellow]Web UI is already running[/yellow] (PID {manager.pid})")
        # Still verify vLLM in case it crashed independently.
        _ensure_vllm_running()
        return

    _print_startup_banner(manager.host, manager.port, background=True)

    if not manager.start():
        error_console.print("[red]Failed to start server process[/red]")
        raise typer.Exit(1)

    # Wait for health check (with early exit if process dies)
    console.print("[dim]Waiting for server to be ready...[/dim]")
    if _wait_for_health(
        manager.host,
        manager.port,
        HEALTH_CHECK_TIMEOUT,
        process_alive=manager.is_running,
    ):
        from aria.config.service import Server

        console.print(f"[green]✓[/green] Server started on {Server.get_base_url()}")
        console.print(f"[dim]PID: {manager.pid}[/dim]")
    else:
        _print_startup_failure(
            _get_captured_startup_error()
            or "Server failed to become healthy within the startup timeout."
        )
        manager.stop()
        raise typer.Exit(1)

    # Verify vLLM is running after web UI is up (safety net in case
    # the Chainlit lifecycle hook failed to start it).
    _ensure_vllm_running()


@app.command("stop")
def server_stop(
    skip_vllm: bool = typer.Option(
        False,
        "--skip-vllm",
        help="Keep vLLM servers running (only stop the web UI).",
    ),
    force_stop: bool = typer.Option(
        False,
        "--force-stop",
        help="Stop even while the knowledge hub is digesting documents.",
    ),
):
    """Stop the Aria webserver.

    Also stops all vLLM server processes managed by the web_ui,
    unless --skip-vllm is specified.

    Refuses to stop while the knowledge hub is digesting documents,
    unless --force-stop is specified.
    """
    if skip_vllm:
        console.print("[dim]vLLM servers will be left running[/dim]")

    result = stop_server(
        skip_vllm=skip_vllm,
        progress=lambda m: console.print(f"[dim]{m}[/dim]"),
        force=force_stop,
    )

    if result.blocked_by_digest:
        console.print("[dim]Use --force-stop to stop anyway.[/dim]")
        raise typer.Exit(1)

    if result.web_stopped:
        console.print("[green]✓[/green] Server stopped")
    else:
        console.print("[yellow]Server is not running[/yellow]")

    if result.vllm_skipped:
        pass
    else:
        from aria.config.api import Vllm as VllmConfig

        if VllmConfig.remote:
            console.print(
                "[dim]Remote vLLM mode — local server management skipped[/dim]"
            )
        else:
            console.print("[green]✓[/green] vLLM servers stopped")

    if not result.web_stopped and not result.vllm_had_pids:
        raise typer.Exit(1)


@app.command("status")
def server_status():
    """Show the current status of the Aria webserver and vLLM servers."""
    from aria.config.models import Chat

    manager = ServerManager()
    status = manager.get_status()

    # WebUI status table
    table = Table(title="Aria Webserver Status", show_header=True)
    table.add_column("Property", style="cyan", width=12)
    table.add_column("Value", style="green")

    # Status with colored indicator
    if status.running:
        table.add_row("Status", "● Running")
    else:
        table.add_row("Status", "○ Stopped")

    # PID
    table.add_row("PID", str(status.pid) if status.pid else "N/A")

    # Host and port
    table.add_row("Host", status.host)
    table.add_row("Port", str(status.port))

    # URL
    from aria.config.service import Server

    table.add_row("URL", Server.get_base_url())

    # Start time
    if status.started_at:
        table.add_row("Started", status.started_at.strftime("%Y-%m-%d %H:%M:%S"))
    else:
        table.add_row("Started", "N/A")

    # Uptime
    if status.uptime_seconds is not None:
        hours, remainder = divmod(int(status.uptime_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        table.add_row("Uptime", uptime_str)
    else:
        table.add_row("Uptime", "N/A")

    console.print(table)

    # vLLM servers status (always show, not just when web_ui is running)
    console.print()
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        # Remote mode — show endpoint info instead of local processes
        vllm_table = Table(title="vLLM (Remote)", show_header=True)
        vllm_table.add_column("Setting", style="cyan", width=16)
        vllm_table.add_column("Value", style="green")
        vllm_table.add_row("Mode", "Remote")
        vllm_table.add_row("Endpoint", Chat.api_url)
        healthy = _is_vllm_healthy()
        vllm_table.add_row(
            "Status",
            "● Reachable" if healthy else "○ Unreachable",
        )
        console.print(vllm_table)
    else:
        vllm_table = Table(title="vLLM Servers", show_header=True)
        vllm_table.add_column("Role", style="cyan", width=12)
        vllm_table.add_column("Port", style="yellow")
        vllm_table.add_column("Status", style="green")

        for role, get_port in [
            ("chat", Chat.get_port),
        ]:
            port = get_port()
            try:
                with urlopen(f"http://localhost:{port}/health", timeout=2) as resp:
                    is_running = resp.status == 200
            except (URLError, OSError):
                is_running = False

            vllm_table.add_row(
                role,
                str(port),
                "● Running" if is_running else "○ Stopped",
            )

        console.print(vllm_table)
