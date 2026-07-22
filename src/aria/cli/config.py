"""Configuration display and optimization commands for the Aria CLI.

This module provides commands to display, inspect, and optimize the
configuration settings for the Aria application.

Commands:
    show: Display all configuration settings (paths + database + api)
    paths: Show all configured file system paths
    database: Show database connection configuration
    api: Show API endpoint configuration
    optimize: Optimize .env settings based on current hardware

Example:
    ```bash
    # Show all configuration
    aria config show

    # Show only paths
    aria config paths

    # Show database configuration
    aria config database

    # Show API configuration
    aria config api

    # Optimize .env for current hardware
    aria config optimize

    # Dry-run (show changes without writing)
    aria config optimize --dry-run
    ```
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aria.config import get_optional_env
from aria.config.database import ChromaDB, SQLite
from aria.config.folders import (
    DB,
    Bin,
    Data,
    Debug,
    Models,
    Storage,
    Workspace,
)
from aria.config.models import Chat, Embeddings

app = typer.Typer(
    name="config",
    help="Configuration display commands.",
)

console = Console()


@app.command("show")
def show_config():
    """Display all configuration settings.

    Runs paths, database, and api sub-commands in sequence.

    Example:
        ```bash
        aria config show
        ```
    """
    show_paths()
    console.print()
    show_database()
    console.print()
    show_api()


@app.command("paths")
def show_paths():
    """Show all configured file system paths.

    Displays a table of all file system paths used by the application:
    - Data folder
    - Storage location
    - Debug logs
    - Database files

    Example:
        ```bash
        aria config paths
        ```
    """
    console.print("[bold]File System Paths[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan", width=20)
    table.add_column("Path", style="green")
    table.add_column("Exists", style="yellow", width=8)

    paths = [
        ("Home", Data.path),
        ("Workspace", Workspace.path),
        ("Bin", Bin.path),
        ("DB", DB.path),
        ("Storage", Storage.path),
        ("Logs", Debug.logs_path),
        ("Models", Models.path),
        ("Database File", SQLite.file_path),
        ("ChromaDB Path", ChromaDB.db_path),
    ]

    for name, path in paths:
        exists = "[green]✓[/green]" if path.exists() else "[red]✗[/red]"
        table.add_row(name, str(path), exists)

    console.print(table)


@app.command("database")
def show_database():
    """Show database connection configuration.

    Displays database connection details including:
    - SQLite file path
    - Connection URLs (sync and async)
    - ChromaDB path

    Example:
        ```bash
        aria config database
        ```
    """
    console.print("[bold]Database Configuration[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan", width=20)
    table.add_column("Value", style="green")

    table.add_row("SQLite File", str(SQLite.file_path))
    table.add_row("Sync URL", SQLite.db_url)
    table.add_row("Async URL", SQLite.conn_info)
    table.add_row("ChromaDB Path", str(ChromaDB.db_path))

    # Check if database exists
    db_exists = SQLite.file_path.exists()
    table.add_row(
        "Database Exists",
        "[green]✓ Yes[/green]" if db_exists else "[red]✗ No[/red]",
    )

    console.print(table)


@app.command("api")
def show_api():
    """Show API configuration.

    Displays API endpoint configuration including:
    - Chat API URL
    - Embeddings API URL and model
    - Token limits

    Example:
        ```bash
        aria config api
        ```
    """
    console.print("[bold]API Configuration[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan", width=20)
    table.add_column("Value", style="green")

    table.add_row("Chat API URL", Chat.api_url)
    table.add_row("Max Iterations", str(Chat.max_iteration))
    table.add_row("Embeddings Model", Embeddings.model)
    table.add_row("Token Limit", str(Embeddings.token_limit))

    console.print(table)


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read .env file and return key-value pairs.

    Preserves ordering and comments. Returns a dict of KEY=VALUE.
    """
    env_vars: dict[str, str] = {}
    if not env_path.exists():
        return env_vars
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            # Strip inline comments (value # comment)
            if " #" in value:
                value = value[: value.index(" #")]
            # Strip quotes from value
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            env_vars[key.strip()] = value
    return env_vars


def _update_env_file(env_path: Path, updates: dict[str, str]) -> list[str]:
    """Update values in .env file. Returns list of keys that were changed.

    If a key doesn't exist, it is appended at the end.
    """
    if not env_path.exists():
        return list(updates.keys())

    content = env_path.read_text()
    changed = []

    for key, new_value in updates.items():
        # Match existing KEY=VALUE (with optional quotes)
        pattern = re.compile(
            rf"^(export\s+)?{re.escape(key)}=(.*?)(\s*#.*)?$", re.MULTILINE
        )
        match = pattern.search(content)
        if match:
            old_value = match.group(2).strip()
            # Strip quotes for comparison
            if (
                len(old_value) >= 2
                and old_value[0] == old_value[-1]
                and old_value[0] in ('"', "'")
            ):
                old_compare = old_value[1:-1]
            else:
                old_compare = old_value
            if old_compare != new_value:
                # Preserve comment if present
                comment = match.group(3) or ""
                prefix = match.group(1) or ""
                replacement = f"{prefix}{key}={new_value}{comment}"
                content = (
                    content[: match.start()] + replacement + content[match.end() :]
                )
                changed.append(key)
        else:
            # Key doesn't exist, append it
            content = content.rstrip() + f"\n{key}={new_value}\n"
            changed.append(key)

    env_path.write_text(content)
    return changed


KV_OFFLOAD_VRAM_THRESHOLD_MB = 12288


@dataclass
class HardwareInfo:
    """Detected hardware summary used for config optimization."""

    gpus: list
    total_vram: int
    free_vram_list: list[int]
    total_ram_mb: int
    avail_ram_mb: int
    gpu_count: int
    has_nvlink: bool


def _collect_hardware() -> HardwareInfo:
    """Detect GPUs, VRAM, and system RAM."""
    from aria.helpers.memory import detect_system_ram
    from aria.helpers.nvidia import (
        detect_gpu_count,
        detect_gpus_with_details,
        detect_nvlink,
        get_free_vram_per_gpu,
        get_total_vram_mb,
    )

    total_ram_mb, avail_ram_mb = detect_system_ram()
    return HardwareInfo(
        gpus=detect_gpus_with_details(),
        total_vram=get_total_vram_mb(),
        free_vram_list=get_free_vram_per_gpu(),
        total_ram_mb=total_ram_mb,
        avail_ram_mb=avail_ram_mb,
        gpu_count=detect_gpu_count(),
        has_nvlink=detect_nvlink()[0],
    )


def _mib_str(mb: int) -> str:
    """Format a megabyte value as ``MiB (GiB)`` or ``N/A`` when zero."""
    return f"{mb} MiB ({mb / 1024:.1f} GiB)" if mb > 0 else "N/A"


def _print_hardware(hw: HardwareInfo) -> None:
    """Render the detected-hardware table."""
    console.print("[bold]Hardware Detected[/bold]\n")
    hw_table = Table(show_header=True, header_style="bold cyan")
    hw_table.add_column("Component", style="cyan", width=16)
    hw_table.add_column("Details", style="green")

    if hw.gpus:
        for i, gpu in enumerate(hw.gpus):
            free_mb = hw.free_vram_list[i] if i < len(hw.free_vram_list) else 0
            hw_table.add_row(
                f"GPU {i}",
                f"{gpu.name} — {gpu.total_memory} MB total, {free_mb} MB free",
            )
    else:
        hw_table.add_row("GPU", "[yellow]No NVIDIA GPU detected[/yellow]")

    hw_table.add_row("GPU Count", str(hw.gpu_count))
    hw_table.add_row("Total VRAM", _mib_str(hw.total_vram))
    hw_table.add_row("NVLink", "✓ Available" if hw.has_nvlink else "✗ No")
    hw_table.add_row("System RAM", _mib_str(hw.total_ram_mb))
    hw_table.add_row("Available RAM", f"{hw.avail_ram_mb} MiB")
    console.print(hw_table)


def _detect_model_sizes() -> dict[str, int]:
    """Return model file sizes (MB) for chat and embeddings models."""
    from aria.helpers.memory import get_model_file_size

    model_files = {"chat": Chat.model_path, "embeddings": Embeddings.model_path}
    sizes: dict[str, int] = {}
    for alias, mp in model_files.items():
        if mp and Path(mp).is_absolute() and Path(mp).exists():
            sizes[alias] = get_model_file_size(Path(mp))
        else:
            sizes[alias] = 0
    return sizes


def _compute_kv_offload_size(chat_ctx: int) -> str:
    """Estimate the KV-offload size (GiB) when auto-offload is active."""
    from aria.helpers.nvidia import _estimate_kv_cache_mb

    kv_mb = _estimate_kv_cache_mb(
        Chat.model_path or "",
        chat_ctx,
        get_optional_env("ARIA_VLLM_KV_CACHE_DTYPE", "auto"),
    )
    if kv_mb and kv_mb > 0:
        return str(math.ceil(kv_mb / 1024))
    return ""


def _compute_optimized(
    hw: HardwareInfo, model_sizes: dict[str, int]
) -> tuple[dict[str, str], dict[str, str]]:
    """Calculate optimized env values and human-readable reasons."""
    from aria.helpers.nvidia import calculate_max_safe_context

    max_free_vram = max(hw.free_vram_list) if hw.free_vram_list else 0
    chat_ctx = calculate_max_safe_context(
        free_vram_mb=max_free_vram,
        model_size_mb=model_sizes.get("chat", 0),
        is_embedding_model=False,
    )
    if chat_ctx == 0:
        chat_ctx = 65536
    embed_ctx = calculate_max_safe_context(
        free_vram_mb=max_free_vram,
        model_size_mb=model_sizes.get("embeddings", 0),
        is_embedding_model=True,
    )
    if embed_ctx == 0:
        embed_ctx = 8192

    low_vram = hw.total_vram < KV_OFFLOAD_VRAM_THRESHOLD_MB
    kv_offload_mode = "auto" if low_vram else "off"
    kv_offloading_size_gb = _compute_kv_offload_size(chat_ctx) if low_vram else ""
    token_limit = max(8192, min(chat_ctx // 4, 65536))

    optimized = {
        "CHAT_CONTEXT_SIZE": str(chat_ctx),
        "EMBEDDINGS_CONTEXT_SIZE": str(embed_ctx),
        "ARIA_VLLM_KV_OFFLOAD_MODE": kv_offload_mode,
        "ARIA_VLLM_KV_OFFLOADING_SIZE_GB": kv_offloading_size_gb,
        "TOKEN_LIMIT": str(token_limit),
        "FORCE_CONTEXT": "true",
    }
    reasons = {
        "CHAT_CONTEXT_SIZE": (
            f"based on {max_free_vram} MB free VRAM"
            if max_free_vram > 0
            else "default (no GPU)"
        ),
        "EMBEDDINGS_CONTEXT_SIZE": (
            f"embedding tier for {max_free_vram} MB VRAM"
            if max_free_vram > 0
            else "default (no GPU)"
        ),
        "ARIA_VLLM_KV_OFFLOAD_MODE": (
            "auto-offload to RAM (VRAM < 12 GB)"
            if low_vram
            else "GPU-only (VRAM ≥ 12 GB)"
        ),
        "ARIA_VLLM_KV_OFFLOADING_SIZE_GB": (
            f"auto-calculated ({kv_offloading_size_gb} GiB)"
            if kv_offloading_size_gb
            else "N/A (offload disabled)"
        ),
        "TOKEN_LIMIT": f"~1/4 of chat context ({chat_ctx})",
        "FORCE_CONTEXT": "use calculated values exactly",
    }
    return optimized, reasons


def _print_diff(
    current: dict[str, str],
    optimized: dict[str, str],
    reasons: dict[str, str],
) -> None:
    """Render the current-vs-optimized comparison table."""
    console.print("\n[bold]Optimized Configuration[/bold]\n")
    opt_table = Table(show_header=True, header_style="bold cyan")
    opt_table.add_column("Setting", style="cyan", width=24)
    opt_table.add_column("Current", style="white", width=12)
    opt_table.add_column("Optimized", style="green", width=12)
    opt_table.add_column("Reason", style="dim")

    for key, new_val in optimized.items():
        old_val = current.get(key, "[dim]not set[/dim]")
        changed = old_val != new_val
        opt_table.add_row(
            key,
            str(old_val),
            f"[bold green]{new_val}[/bold green]" if changed else str(new_val),
            reasons.get(key, ""),
        )
    console.print(opt_table)


@app.command("optimize")
def optimize_config(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show changes without writing to .env"),
    ] = False,
):
    """Optimize .env configuration based on current hardware.

    Detects GPU VRAM, system RAM, and downloaded models, then calculates
    the optimal context sizes, KV cache placement, and token limits.

    Example:
        ```bash
        # Optimize and write to .env
        aria config optimize

        # Preview changes without writing
        aria config optimize --dry-run
        ```
    """
    hw = _collect_hardware()
    if not hw.gpus:
        raise typer.BadParameter(
            "No GPU detected; cannot optimize. Set CHAT_CONTEXT_SIZE manually."
        )

    _print_hardware(hw)
    optimized, reasons = _compute_optimized(hw, _detect_model_sizes())
    _print_diff(_read_env_file(Path(".env")), optimized, reasons)

    if dry_run:
        console.print(
            "\n[yellow]Dry run — no changes written. "
            "Run without --dry-run to apply.[/yellow]"
        )
        return

    changed_keys = _update_env_file(Path(".env"), optimized)
    if changed_keys:
        console.print(
            f"\n[green]✓ .env updated with {len(changed_keys)} "
            f"optimized value(s): {', '.join(changed_keys)}[/green]"
        )
    else:
        console.print("\n[dim]✓ .env is already optimal — no changes needed.[/dim]")
