"""Docling worker management commands.

Commands:
    install: Build the isolated docling venv + shim.
    download: Pre-fetch the Granite-Docling model snapshot.
    status: Show worker install state, model cached, resolved device.
    uninstall: Remove the isolated docling venv + shim.

Example:
    ```bash
    aria docling install
    aria docling download
    aria docling status
    ```
"""

from pathlib import Path
from typing import Annotated

import typer
from huggingface_hub import snapshot_download
from rich.console import Console
from rich.table import Table

from aria.config.huggingface import HuggingFace
from aria.config.models import _resolve_model_path
from aria.config.pdf import Pdf

app = typer.Typer(name="docling", help="Granite-Docling worker management.")
console = Console()
error_console = Console(stderr=True, style="bold red")


@app.command("install")
def install_command() -> None:
    """Build the isolated docling venv + ~/.aria/bin/docling shim."""
    from aria.scripts.docling import install_docling

    try:
        install_docling()
        console.print("[green]✓[/green] docling worker installed")
    except Exception as e:
        error_console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command("download")
def download_command(
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="HuggingFace API token. Falls back to HF_TOKEN env var.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-F",
            help="Force re-download even if the model already exists.",
        ),
    ] = False,
) -> None:
    """Pre-fetch the Granite-Docling model snapshot.

    Downloads ``ARIA_DOCLING_MODEL`` (default
    ``ibm-granite/granite-docling-258M``) to ``~/.aria/models/<name>/``
    so the first PDF conversion doesn't block on a multi-hundred-MB
    download. Run after ``aria docling install``.

    Example:
        ```bash
        aria docling download
        aria docling download --force
        ```
    """
    repo_id = Pdf.vlm_model_id
    local_dir = _resolve_model_path(repo_id)
    resolved_token = token or HuggingFace.token

    console.print("[bold]Granite-Docling Model Download[/bold]")
    console.print(f"  Repo: {repo_id}")
    console.print(f"  Destination: {local_dir}")
    token_status = (
        "[green]set[/green]"
        if resolved_token
        else "[yellow]not set (public only)[/yellow]"
    )
    console.print(f"  Token: {token_status}")
    if force:
        console.print("  [yellow]Force: yes[/yellow]")
    console.print()

    download_kwargs: dict = {
        "repo_id": repo_id,
        "local_dir": local_dir,
        "token": resolved_token,
        "ignore_patterns": ["onnx/*", "openvino/*", "openvino_model.*"],
    }
    if force:
        download_kwargs["force_download"] = True

    try:
        dest = snapshot_download(**download_kwargs)
        console.print(f"[green]✓[/green] Model ready at: [dim]{dest}[/dim]")
        console.print(
            "[dim]The worker resolves this automatically from "
            f"{repo_id} — no env var needed.[/dim]"
        )
    except Exception as e:
        error_console.print(f"[red]✗[/red] Download failed: {e}")
        raise typer.Exit(1)


@app.command("status")
def status_command() -> None:
    """Show worker install state, model cached, resolved device.

    Example:
        ```bash
        aria docling status
        ```
    """
    from aria.config.folders import Bin
    from aria.config.pdf import DoclingVenv
    from aria.scripts.docling import detect_device, is_installed

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan", width=20)
    table.add_column("Value", style="green")

    if is_installed():
        device = Pdf.vlm_device
        if device == "auto":
            device = detect_device()
        model_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
        model_cached = bool(model_path) and Path(model_path).is_dir()

        table.add_row("Worker", "[green]✓ Installed[/green]")
        table.add_row("Model", Pdf.vlm_model_id)
        table.add_row("Device", device)
        table.add_row(
            "Model cached",
            "[green]✓ Yes[/green]"
            if model_cached
            else "[dim]No (run: aria docling download)[/dim]",
        )
        table.add_row("Venv", str(DoclingVenv.get_venv_path()))
        table.add_row("Shim", str(Bin.path / "docling"))
    else:
        table.add_row("Worker", "[red]✗ Not installed[/red]")
        table.add_row("Install", "Run: aria docling install")

    console.print(table)


@app.command("uninstall")
def uninstall_command() -> None:
    """Remove the isolated docling venv + shim."""
    from aria.scripts.docling import uninstall_docling

    try:
        uninstall_docling()
        console.print("[green]✓[/green] docling worker removed")
    except Exception as e:
        error_console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
