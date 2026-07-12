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

from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aria.config.folders import Debug as DebugConfig
from aria.preflight import run_preflight_checks
from aria.server import ServerManager

app = typer.Typer(
    name="server",
    help="Manage the Aria webserver",
)
console = Console()
error_console = Console(stderr=True, style="bold red")

# Health check settings
HEALTH_CHECK_TIMEOUT = 180  # seconds (vLLM model loading can take 30s+)
HEALTH_CHECK_INTERVAL = 0.5  # seconds


def _authenticated_request(url: str, timeout: float = 5):
    """Open a URL with the vLLM API key when in remote mode.

    Remote vLLM servers enforce ``--api-key`` auth, so every request
    must carry ``Authorization: Bearer <key>``.  Local mode leaves the
    key unset (``sk-aria`` default) and the local server doesn't check,
    so the header is harmless.
    """
    from aria.config.api import Vllm as VllmConfig

    headers = {}
    if VllmConfig.remote and VllmConfig.api_key:
        headers["Authorization"] = f"Bearer {VllmConfig.api_key}"
    req = Request(url, headers=headers)
    return urlopen(req, timeout=timeout)


def _print_startup_banner(host: str, port: int, background: bool = False) -> None:
    mode = "Background" if background else "Foreground"
    action = "Starting Aria Web UI"
    from aria.helpers.network import resolve_display_host

    display_host = resolve_display_host(host)
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{action}[/bold cyan]\n"
            f"[white]{display_host}:{port}[/white]"
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
    """Print preflight results in grouped format and return True if all pass."""
    grouped = result.group_by_category()

    # Category icons and labels — ordered for logical flow
    # Hardware first (most impactful), then environment, then rest
    category_config = {
        "hardware": {"icon": "🖥️ ", "label": "Hardware"},
        "environment": {"icon": "📦", "label": "Environment"},
        "models": {"icon": "🧠", "label": "Models"},
        "binaries": {"icon": "⚙️ ", "label": "Binaries"},
        "storage": {"icon": "📁", "label": "Storage"},
        "connectivity": {"icon": "🌐", "label": "Connectivity"},
        "tools": {"icon": "🔧", "label": "Tools"},
    }

    for category in category_config.keys():
        if category not in grouped:
            continue

        config = category_config[category]
        checks = grouped[category]
        passed = sum(1 for c in checks if c.passed)

        if passed == len(checks):
            console.print(
                f"{config['icon']} {config['label']} "
                f"[green]{passed}/{len(checks)}[/green]"
            )
        else:
            console.print(
                f"{config['icon']} {config['label']} [red]{passed}/{len(checks)}[/red]"
            )

        for check in checks:
            if check.passed:
                details = f" [dim]({check.details})[/dim]" if check.details else ""
                console.print(f"   [green]✓[/green] {check.name}{details}")
            else:
                console.print(
                    f"   [red]✗[/red] {check.name} — [red]{check.error}[/red]"
                )
                if check.hint:
                    console.print(f"     [dim]→ {check.hint}[/dim]")

    console.print()
    return result.passed


def _wait_for_health(
    host: str,
    port: int,
    timeout: float,
    *,
    process_alive: Callable[[], bool] | None = None,
) -> bool:
    """Wait for server to become healthy.

    Args:
        host: Server host address.
        port: Server port.
        timeout: Maximum seconds to wait.
        process_alive: Optional callable that returns False if the
            subprocess has died, enabling early exit instead of
            polling until the full timeout expires.

    Returns:
        True if server is healthy, False if timeout or process died.
    """
    import time

    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout

    while time.time() < deadline:
        # Early exit if the subprocess crashed
        if process_alive is not None and not process_alive():
            return False
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (URLError, OSError):
            pass
        time.sleep(HEALTH_CHECK_INTERVAL)

    return False


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
        error_console.print(
            "\n[red]✗ Preflight checks failed. Fix the issues above.[/red]"
        )
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
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat

    if VllmConfig.remote:
        # In remote mode, check the configured API URL directly
        try:
            with _authenticated_request(f"{Chat.api_url}/models", timeout=5) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    port = Chat.get_port()
    try:
        with urlopen(f"http://localhost:{port}/health", timeout=2) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def _ensure_lightpanda_installed() -> None:
    """Download Lightpanda automatically if it is missing."""
    from aria.config.api import Lightpanda

    if Lightpanda.is_available():
        console.print("[green]✓[/green] Lightpanda installed")
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


def _ensure_models_downloaded() -> None:
    """Auto-download models from HuggingFace if they are missing.

    Checks each configured model (chat, embeddings). If the model
    directory does not exist locally and the env var contains a
    HuggingFace repo ID (not an absolute path), downloads the
    snapshot automatically with a progress indicator and retry logic.
    """
    from os import getenv
    from pathlib import Path

    from huggingface_hub import snapshot_download
    from rich.status import Status

    from aria.config.api import Vllm as VllmConfig
    from aria.config.huggingface import HuggingFace
    from aria.config.models import Chat, Embeddings

    models_to_check = [
        ("chat", "CHAT_MODEL_PATH", Chat),
        ("embeddings", "EMBED_MODEL_PATH", Embeddings),
    ]

    # In remote mode the chat model is served by an external vLLM endpoint,
    # so we must never attempt to download it locally.  Only the in-process
    # embeddings model still needs to be present on disk.
    if VllmConfig.remote:
        models_to_check = [m for m in models_to_check if m[0] != "chat"]

    max_retries = 3

    for alias, env_var, config_cls in models_to_check:
        model_path = config_cls.model_path
        if not model_path:
            continue  # Not configured — preflight will report it

        path = Path(model_path)
        if path.exists() and path.is_dir():
            console.print(f"[green]✓[/green] {alias} model ready")
            continue

        # Only auto-download for HuggingFace repo IDs (not absolute paths)
        raw_value = getenv(env_var, "")
        if not raw_value or Path(raw_value).is_absolute():
            continue  # Missing or local path that doesn't exist

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            label = (
                f"Downloading {alias} model ({raw_value})"
                if attempt == 1
                else (
                    f"Retrying {alias} model download (attempt {attempt}/{max_retries})"
                )
            )
            try:
                with Status(f"[dim]{label}…[/dim]", console=console):
                    snapshot_download(
                        repo_id=raw_value,
                        local_dir=str(path),
                        token=HuggingFace.token,
                        ignore_patterns=[
                            "onnx/*",
                            "openvino/*",
                            "openvino_model.*",
                        ],
                    )
                console.print(f"[green]✓[/green] {alias} model ready at {path}")
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    console.print(
                        f"[yellow]⚠[/yellow] {alias} model download failed "
                        f"(attempt {attempt}/{max_retries}): {e}"
                    )

        if last_error is not None:
            error_console.print(
                f"[red]Failed to download {alias} model after "
                f"{max_retries} attempts: {last_error}[/red]"
            )
            raise typer.Exit(1)


def _has_cuda() -> bool:
    """Check if CUDA-capable hardware is available."""
    try:
        from aria.helpers.nvidia import get_total_vram_mb

        return get_total_vram_mb() > 0
    except Exception:
        return False


def _ensure_endpoint_reachable() -> None:
    """Verify the OpenAI-compatible endpoint is reachable.

    This is the final gate before starting the server. If the endpoint
    is not healthy, the server will not start.

    - Remote mode: test the configured endpoint URL (fail-fast).
    - Local mode with CUDA: start vLLM if needed, then verify health.
    - Local mode without CUDA: fail with guidance to use remote mode.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat

    # ── Remote mode ──────────────────────────────────────────────────────
    if VllmConfig.remote:
        try:
            with _authenticated_request(f"{Chat.api_url}/models", timeout=10) as resp:
                if resp.status == 200:
                    console.print("[green]✓[/green] Remote OpenAI endpoint reachable")
                    return
        except (URLError, OSError) as e:
            error_console.print(
                f"[red]✗[/red] Remote OpenAI endpoint unreachable: "
                f"{Chat.api_url}\n  {e}"
            )
            raise typer.Exit(1)

    # ── Local mode — CUDA required ───────────────────────────────────────
    if not _has_cuda():
        error_console.print(
            "[red]✗[/red] No CUDA-capable GPU detected. "
            "Local vLLM requires NVIDIA CUDA drivers.\n"
            "  Set [bold]ARIA_VLLM_REMOTE=true[/bold] in your .env "
            "to connect to a remote OpenAI-compatible endpoint."
        )
        raise typer.Exit(1)

    # ── Local mode with CUDA — ensure vLLM is running ────────────────────
    # Check if vLLM is already healthy
    try:
        port = Chat.get_port()
        with urlopen(f"http://localhost:{port}/health", timeout=3) as resp:
            if resp.status == 200:
                console.print("[green]✓[/green] OpenAI endpoint already running")
                return
    except (URLError, OSError):
        pass  # Not running — will start below

    # Start vLLM explicitly
    from aria.server.vllm import VllmServerManager

    console.print("[dim]Starting vLLM server...[/dim]")
    try:
        vllm = VllmServerManager()
        vllm.start_all()
    except Exception as e:
        error_console.print(f"[red]✗[/red] Failed to start vLLM: {e}")
        raise typer.Exit(1)

    # Poll for health (model loading can take 30s+)
    import time

    port = Chat.get_port()
    vllm_timeout = 120  # seconds
    deadline = time.time() + vllm_timeout
    console.print("[dim]Waiting for vLLM to become healthy...[/dim]")

    while time.time() < deadline:
        try:
            with urlopen(f"http://localhost:{port}/health", timeout=3) as resp:
                if resp.status == 200:
                    console.print("[green]✓[/green] OpenAI endpoint healthy")
                    return
        except (URLError, OSError):
            pass
        time.sleep(HEALTH_CHECK_INTERVAL)

    error_console.print(
        "[red]✗[/red] OpenAI endpoint unhealthy after vLLM startup. "
        "Check vLLM logs for details."
    )
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
        error_console.print(
            "\n[red]✗ Preflight checks failed. Fix the issues above.[/red]"
        )
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
):
    """Stop the Aria webserver.

    Also stops all vLLM server processes managed by the web_ui,
    unless --skip-vllm is specified.
    """
    if skip_vllm:
        from aria.config.folders import Data as DataConfig

        sentinel = DataConfig.path / "skip_vllm_shutdown"
        sentinel.touch()
        console.print("[dim]vLLM servers will be left running[/dim]")

    # Snapshot vLLM PIDs BEFORE stopping the web server, because the
    # Chainlit shutdown handler may clear the PID file during teardown.
    vllm_pids: dict[str, int] = {}
    if not skip_vllm:
        from aria.server.vllm import VllmServerManager

        vllm_pids = VllmServerManager()._pids.copy()

    manager = ServerManager()
    web_stopped = manager.stop()
    if web_stopped:
        console.print("[green]✓[/green] Server stopped")
    else:
        console.print("[yellow]Server is not running[/yellow]")

    # Always attempt to stop vLLM — even if the web server was already dead,
    # vLLM may still be alive as an orphan process.
    if not skip_vllm:
        from aria.config.api import Vllm as VllmConfig

        if VllmConfig.remote:
            console.print(
                "[dim]Remote vLLM mode — local server management skipped[/dim]"
            )
        else:
            from aria.server.vllm import VllmServerManager

            vllm = VllmServerManager()
            # Merge pre-snapshot PIDs with any currently tracked PIDs
            live_pids = {**vllm_pids, **vllm._pids}
            if live_pids:
                vllm._pids = live_pids
            # Always call stop_all — it now scans for orphaned
            # processes even when the PID file is stale or empty.
            console.print("[dim]Stopping vLLM servers...[/dim]")
            vllm.stop_all()
            console.print("[green]✓[/green] vLLM servers stopped")

    if not web_stopped and not vllm_pids:
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
