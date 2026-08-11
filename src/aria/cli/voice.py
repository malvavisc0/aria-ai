"""Voice assistant component management commands for the Aria CLI.

Provides commands to download and check the whisper.cpp (STT) and
kokoro-tts (TTS) components. Mirrors ``cli/lightpanda.py``.

Commands:
    download: Download whisper.cpp + kokoro-tts and their models
    status: Check installed voice components and status
"""

import typer
from rich.console import Console
from rich.table import Table

from aria.config.api import Voice
from aria.config.folders import Bin, Models
from aria.scripts.voice import download_kokoro, download_whisper_cpp

app = typer.Typer(
    name="voice",
    help="Voice assistant component management commands.",
)

console = Console()
error_console = Console(stderr=True, style="bold red")


@app.command("download")
def download_command(
    model: str = typer.Option(
        None, help="Whisper GGUF model to download (default: Voice.whisper_model)"
    ),
):
    """Download whisper.cpp (STT) and kokoro-tts (TTS) components.

    Fetches the whisper.cpp server binary and GGUF model, installs the
    kokoro-tts tool via ``uv tool install`` (isolated env), and downloads
    the kokoro ONNX model + voices file.

    Example:
        ```bash
        aria voice download
        ```
    """
    try:
        console.print("[bold]=> Whisper.cpp (STT)[/bold]")
        download_whisper_cpp(model=model or Voice.whisper_model)
        console.print("[bold]=> Kokoro TTS[/bold]")
        download_kokoro()
        console.print("[green]✓[/green] Voice components installed")
    except Exception as e:
        error_console.print(f"[red]✗[/red] Installation failed: {e}")
        raise typer.Exit(1)


@app.command("status")
def check_status():
    """Check installed voice component status.

    Displays the whisper.cpp binary, GGUF model, kokoro model directory,
    and whether voice features are available.

    Example:
        ```bash
        aria voice status
        ```
    """
    console.print("[bold]Voice Assistant Status[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Property", style="cyan", width=20)
    table.add_column("Value", style="green")

    table.add_row("Bin Directory", str(Bin.path))
    table.add_row("Models Directory", str(Models.path))
    table.add_row(
        "Enabled", "[green]true[/green]" if Voice.enabled else "[yellow]false[/yellow]"
    )
    table.add_row("Whisper Model", Voice.whisper_model)
    table.add_row("Whisper Port", str(Voice.whisper_port))
    table.add_row("Kokoro Voice", Voice.kokoro_voice)
    table.add_row("Kokoro Lang", Voice.kokoro_lang)

    if not Voice.enabled:
        table.add_row(
            "Voice Features", "[yellow]Disabled (ARIA_VOICE_ENABLED=false)[/yellow]"
        )
    else:
        whisper = Voice.get_whisper_binary_path()
        if whisper:
            table.add_row("Whisper Binary", str(whisper))
            table.add_row("Whisper Model File", str(Voice.get_whisper_model_path()))
            build_tag = whisper.parent / ".build_type"
            if build_tag.is_file():
                table.add_row("Build Type", build_tag.read_text().strip())
            else:
                table.add_row("Build Type", "[dim]unknown[/dim]")
        else:
            table.add_row("Whisper", "[yellow]✗ Not installed[/yellow]")

        if Voice.is_kokoro_available():
            table.add_row("Kokoro Model", str(Voice.get_kokoro_model_path()))
        else:
            table.add_row("Kokoro Model", "[yellow]✗ Not installed[/yellow]")

        if Voice.is_available():
            table.add_row("Voice Features", "[green]Available[/green]")
        else:
            table.add_row("Voice Features", "[yellow]Disabled[/yellow]")
            table.add_row("Install Command", "aria voice download")

    console.print(table)
