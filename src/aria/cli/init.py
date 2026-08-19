"""``aria init`` — bootstrap Aria_HOME, detect hardware, pick a chat mode,
install binaries, and download models.

Splits all initialization out of the ``aria server start`` hot path. The
feature matrix (chat mode × GPU) lives in :mod:`aria.bootstrap`; this
command drives it and prints a progress + summary report.

Flow (plan §4): bootstrap → detect → choose mode → apply features →
install binaries → download models → small-GPU warn → preflight → summary.
Any failure aborts with a non-zero exit and a hint (fail fast, no partial
state silently kept). Idempotent: re-runs skip already-installed pieces.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aria.bootstrap import (
    CHAT_MODE_LOCAL,
    CHAT_MODE_REMOTE,
    FeatureChoices,
    HardwareProfile,
    detect_hardware,
    is_init_completed,
    run_init,
)

app = typer.Typer(
    name="init",
    help="Bootstrap ARIA_HOME, detect hardware, install binaries, and "
    "download models. Run once before `aria server start`.",
    invoke_without_command=False,
)
console = Console()
error_console = Console(stderr=True, style="bold red")


def _print_hardware_summary(hw: HardwareProfile) -> None:
    if hw.has_nvidia_gpu:
        gb = hw.vram_mb / 1024
        cuda = hw.cuda_version or "unknown"
        console.print(
            f"[green]✓[/green] NVIDIA GPU detected: {gb:.0f} GB VRAM, CUDA {cuda}"
        )
    elif hw.has_rocm:
        console.print(
            "[yellow]⚠[/yellow] AMD ROCm detected — local chat is NVIDIA-only "
            "this iteration. Use Remote mode."
        )
    else:
        console.print("[dim]No NVIDIA GPU detected. Remote mode required.[/dim]")


def _prompt_mode_interactive(hw: HardwareProfile) -> str:
    """Interactive mode choice (default: local when GPU present)."""
    if not hw.has_nvidia_gpu:
        console.print(
            "[red]No NVIDIA GPU detected — local chat is not available.[/red]"
        )
        return _prompt_remote_endpoint_interactive()
    default_local = "local"
    choice = (
        typer.prompt(
            "Chat mode",
            default=default_local,
            prompt_suffix=" [local/remote]: ",
        )
        .strip()
        .lower()
    )
    if choice == "local":
        return CHAT_MODE_LOCAL
    if choice == "remote":
        return _prompt_remote_endpoint_interactive()
    raise typer.BadParameter("mode must be 'local' or 'remote'")


def _prompt_remote_endpoint_interactive() -> str:
    """Prompt for remote endpoint fields and probe reachability. Returns remote mode."""
    from aria.server.lifecycle import _remote_endpoint_reachable

    url = typer.prompt("Remote endpoint URL (e.g. https://api.openai.com/v1)")
    api_key = typer.prompt("API key", hide_input=True)
    model = typer.prompt("Model name")
    # Probe before accepting — fail fast at init, not at first server start.
    os.environ["CHAT_OPENAI_API"] = url
    os.environ["ARIA_VLLM_API_KEY"] = api_key
    os.environ["CHAT_MODEL"] = model
    os.environ["ARIA_VLLM_REMOTE"] = "true"
    from aria.config import reload_env

    reload_env()
    result = _remote_endpoint_reachable()
    if not result.ok:
        raise typer.BadParameter(
            result.error or "Remote endpoint unreachable",
            param_hint="--remote-url / CHAT_OPENAI_API",
        )
    console.print("[green]✓[/green] Remote endpoint reachable")
    return CHAT_MODE_REMOTE


def _resolve_mode_non_interactive(hw: HardwareProfile) -> tuple[str, FeatureChoices]:
    """Derive chat mode from env vars (Docker path). No prompts, no TTY."""
    remote = os.environ.get("ARIA_VLLM_REMOTE", "").strip().lower() == "true"
    has_remote_env = all(
        os.environ.get(k)
        for k in ("CHAT_OPENAI_API", "ARIA_VLLM_API_KEY", "CHAT_MODEL")
    )
    if remote and not has_remote_env:
        raise typer.BadParameter(
            "ARIA_VLLM_REMOTE=true but CHAT_OPENAI_API / ARIA_VLLM_API_KEY / "
            "CHAT_MODEL are not all set",
        )
    if remote:
        return CHAT_MODE_REMOTE, FeatureChoices()
    if not hw.has_nvidia_gpu:
        raise typer.BadParameter(
            "No NVIDIA GPU detected and ARIA_VLLM_REMOTE is not true. "
            "Local vLLM requires NVIDIA CUDA. Set ARIA_VLLM_REMOTE=true "
            "and configure a remote OpenAI-compatible endpoint.",
        )
    return CHAT_MODE_LOCAL, FeatureChoices()


def _resolve_voice_choice(
    no_voice: bool, with_voice: bool, hw: HardwareProfile
) -> bool | None:
    """Resolve the voice opt-in from flags / env, honoring the no-GPU rule."""
    if not hw.has_nvidia_gpu:
        return False  # decided: no CPU voice
    if with_voice:
        return True
    if no_voice:
        return False
    current = os.environ.get("ARIA_VOICE_ENABLED", "").strip().lower()
    if current == "true":
        return True
    if current == "false":
        return False
    return None  # not set → interactive prompt (or default off)


def _resolve_vision_choice(no_vision: bool, with_vision: bool) -> bool | None:
    if with_vision:
        return True
    if no_vision:
        return False
    current = os.environ.get("ARIA_VLLM_VISION_ENABLED", "").strip().lower()
    if current == "true":
        return True
    if current == "false":
        return False
    return None


def _install_binaries(
    mode: str, hw: HardwareProfile, voice_enabled: bool, dry_run: bool
) -> list[str]:
    """Install binaries (plan step 5). Returns the list of installed labels."""
    if dry_run:
        console.print("[dim][dry-run] would install binaries[/dim]")
        return []
    installed: list[str] = []
    from aria.config.api import Lightpanda
    from aria.server.lifecycle import ensure_lightpanda_installed

    was_installed = Lightpanda.is_available()
    ensure_lightpanda_installed(progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    if not was_installed:
        installed.append("lightpanda")
    if was_installed:
        console.print("[green]✓[/green] Lightpanda already installed")

    if mode == CHAT_MODE_LOCAL:
        from aria.scripts.vllm import install_vllm, is_vllm_installed

        if not is_vllm_installed():
            console.print("[cyan]→[/cyan] Installing vLLM (CUDA target)...")
            install_vllm()
            installed.append("vllm")
        else:
            console.print("[green]✓[/green] vLLM already installed")
    else:
        console.print("[dim]Remote mode — skipping vLLM install[/dim]")

    from aria.scripts.docling import install_docling
    from aria.scripts.docling import is_installed as docling_installed

    if not docling_installed():
        console.print("[cyan]→[/cyan] Installing docling worker...")
        install_docling()
        installed.append("docling")
    else:
        console.print("[green]✓[/green] docling worker already installed")

    if voice_enabled:
        installed.extend(_install_voice())
    return installed


def _install_voice() -> list[str]:
    """Install whisper.cpp + kokoro-tts (CUDA build when a GPU is present)."""
    from aria.config.api import Voice

    installed: list[str] = []
    if Voice.get_whisper_binary_path() is None:
        from aria.scripts.voice import download_whisper_cpp

        console.print("[cyan]→[/cyan] Downloading whisper.cpp (CUDA build)...")
        download_whisper_cpp()
        installed.append("whisper.cpp")
    else:
        console.print("[green]✓[/green] whisper.cpp already installed")
    if not Voice.is_kokoro_available() or Voice.get_kokoro_python() is None:
        from aria.scripts.voice import download_kokoro

        console.print("[cyan]→[/cyan] Downloading kokoro-tts...")
        download_kokoro()
        installed.append("kokoro-tts")
    else:
        console.print("[green]✓[/green] kokoro-tts already installed")
    return installed


def _download_chat_and_embeddings(mode: str) -> list[str]:
    """Download chat (local only) + embeddings via the shared building block.

    Returns the aliases that were newly downloaded (remote-skip and
    skip-if-present are handled by ``ensure_models_downloaded``).
    """
    from aria.config.models import Chat, Embeddings
    from aria.server.lifecycle import ensure_models_downloaded

    candidates: list[tuple[str, str]] = []
    if mode == CHAT_MODE_LOCAL:
        candidates.append(("chat", Chat.model_path))
    candidates.append(("embeddings", Embeddings.model_path))
    present_before = {alias: bool(p and Path(p).is_dir()) for alias, p in candidates}
    ensure_models_downloaded(progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    return [
        alias
        for alias, p in candidates
        if not present_before.get(alias) and p and Path(p).is_dir()
    ]


def _download_docling_model() -> str | None:
    """Download the docling model if missing; return ``"docling"`` if downloaded."""
    from aria.config.models import _resolve_model_path
    from aria.config.pdf import Pdf

    docling_path = Pdf.model_path or _resolve_model_path(Pdf.vlm_model_id)
    if Path(docling_path).is_dir():
        console.print("[green]✓[/green] Docling model already downloaded")
        return None
    console.print(f"[cyan]→[/cyan] Downloading docling model {Pdf.vlm_model_id}...")
    from aria.server.lifecycle import download_model_snapshot

    download_model_snapshot("docling", Pdf.vlm_model_id, Path(docling_path))
    return "docling"


def _download_models(
    mode: str, hw: HardwareProfile, voice_enabled: bool, dry_run: bool
) -> list[str]:
    """Download models (plan step 6). Returns the list of downloaded labels."""
    if dry_run:
        console.print("[dim][dry-run] would download models[/dim]")
        return []
    downloaded = _download_chat_and_embeddings(mode)
    if (label := _download_docling_model()) is not None:
        downloaded.append(label)
    # whisper GGUF + kokoro ONNX were fetched by the voice install step.
    return downloaded


def _print_summary(report, installed: list[str], downloaded: list[str]) -> None:
    table = Table(title="Aria init complete", show_header=True)
    table.add_column("Property", style="cyan", width=18)
    table.add_column("Value", style="green")
    table.add_row("Chat mode", report.chat_mode)
    gpu = "yes" if report.hardware.has_nvidia_gpu else "no"
    table.add_row("NVIDIA GPU", gpu)
    if report.tier and report.tier.chat_model:
        table.add_row("Tier model", report.tier.chat_model)
        table.add_row("Tier context", str(report.tier.context_size))
        table.add_row("Tier quant", report.tier.quant or "")
    if report.changed_env_keys:
        table.add_row(".env changed", ", ".join(report.changed_env_keys))
    if installed:
        table.add_row("Installed", ", ".join(installed))
    if downloaded:
        table.add_row("Downloaded", ", ".join(downloaded))
    console.print(table)
    if report.warning:
        console.print(f"[yellow]⚠ {report.warning}[/yellow]")
    console.print(
        Panel(
            "[bold]Next:[/bold] run [cyan]aria server start[/cyan] to launch.",
            border_style="green",
            expand=False,
            padding=(0, 2),
        )
    )


def _validate_mode(mode: str | None, hw: HardwareProfile) -> None:
    """Validate an explicit --mode value (Decision 1: local needs NVIDIA)."""
    if mode is None:
        return
    if mode not in (CHAT_MODE_LOCAL, CHAT_MODE_REMOTE):
        raise typer.BadParameter("mode must be 'local' or 'remote'")
    if mode == CHAT_MODE_LOCAL and not hw.has_nvidia_gpu:
        raise typer.BadParameter(
            "Local chat requires an NVIDIA GPU. Use --mode remote and "
            "configure a remote OpenAI-compatible endpoint, or set "
            "ARIA_VLLM_REMOTE=true.",
        )


def _abort_no_gpu_no_mode(hw: HardwareProfile) -> None:
    """Refuse a non-interactive, no-GPU, no-mode run (Decision 1)."""
    if not hw.has_nvidia_gpu:
        raise typer.BadParameter(
            "No NVIDIA GPU and no --mode given (non-interactive context). "
            "Run with --mode remote, or set ARIA_VLLM_REMOTE=true.",
        )


def _resolve_chat_mode(
    mode: str | None,
    hw: HardwareProfile,
    non_interactive: bool,
    dry_run: bool,
) -> str:
    """Resolve the chat mode from flags / env / interactive prompt."""
    _validate_mode(mode, hw)

    if non_interactive:
        resolved, _ = _resolve_mode_non_interactive(hw)
        return resolved
    if mode is not None:
        return mode
    if not sys.stdin.isatty() and not dry_run:
        _abort_no_gpu_no_mode(hw)
    if dry_run:
        return CHAT_MODE_LOCAL
    return _prompt_mode_interactive(hw)


def _default_none_to_false(non_interactive: bool, choice: bool | None) -> bool | None:
    """In non-interactive mode, an unset choice defaults to False."""
    if non_interactive and choice is None:
        return False
    return choice


def _build_choices(
    resolved_mode: str,
    hw: HardwareProfile,
    non_interactive: bool,
    remote_url: str | None,
    api_key: str | None,
    model: str | None,
    with_voice: bool,
    no_voice: bool,
    with_vision: bool,
    no_vision: bool,
) -> FeatureChoices:
    """Assemble the FeatureChoices from flags / env / mode."""
    has_remote_fields = resolved_mode == CHAT_MODE_REMOTE and (
        remote_url or api_key or model
    )
    remote_url_v = remote_url or "" if has_remote_fields else ""
    remote_key_v = api_key or "" if has_remote_fields else ""
    remote_model_v = model or "" if has_remote_fields else ""

    voice = _default_none_to_false(
        non_interactive, _resolve_voice_choice(no_voice, with_voice, hw)
    )
    vision = _default_none_to_false(
        non_interactive, _resolve_vision_choice(no_vision, with_vision)
    )
    return FeatureChoices(
        vision=vision,
        voice=voice,
        remote_url=remote_url_v,
        remote_api_key=remote_key_v,
        remote_model=remote_model_v,
    )


def _verify_preflight(dry_run: bool) -> None:
    """Run preflight (step 8); exit 1 on hard failure."""
    if dry_run:
        return
    from aria.preflight import run_preflight_checks

    result = run_preflight_checks()
    if not result.passed:
        for failure in result.failures:
            error_console.print(f"[red]✗[/red] {failure.name}: {failure.error}")
            if failure.hint:
                error_console.print(f"[dim]  → {failure.hint}[/dim]")
        raise typer.Exit(1)
    console.print("[green]✓[/green] Preflight passed")


@app.callback(invoke_without_command=True)
def init_command(
    mode: Annotated[
        str | None,
        typer.Option("--mode", help="Chat mode: local or remote."),
    ] = None,
    remote_url: Annotated[
        str | None, typer.Option("--remote-url", help="Remote endpoint URL.")
    ] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="Remote endpoint API key.")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Remote model name.")
    ] = None,
    with_voice: Annotated[
        bool, typer.Option("--with-voice", help="Enable voice assistant.")
    ] = False,
    no_voice: Annotated[
        bool, typer.Option("--no-voice", help="Disable voice assistant.")
    ] = False,
    with_vision: Annotated[
        bool, typer.Option("--with-vision", help="Enable vision/image uploads.")
    ] = False,
    no_vision: Annotated[
        bool, typer.Option("--no-vision", help="Disable vision/image uploads.")
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Derive everything from env vars (Docker); no prompts.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the plan, change nothing."),
    ] = False,
) -> None:
    """Bootstrap ARIA_HOME, detect hardware, install binaries, download models."""
    # Step 1 — bootstrap (idempotent: env file, dirs, DB, logs, assets, chainlit config)
    from aria.initializer import (
        is_initialized,
        run_initialization,
        setup_chainlit_config,
        setup_public_assets,
    )

    if not is_initialized():
        console.print("[cyan]→[/cyan] Bootstrapping ARIA_HOME...")
        run_initialization()
    setup_public_assets()
    setup_chainlit_config()

    # Step 2 — detect hardware
    hw = detect_hardware()
    _print_hardware_summary(hw)

    # Step 3 — choose chat mode + build choices
    resolved_mode = _resolve_chat_mode(mode, hw, non_interactive, dry_run)
    choices = _build_choices(
        resolved_mode,
        hw,
        non_interactive,
        remote_url,
        api_key,
        model,
        with_voice,
        no_voice,
        with_vision,
        no_vision,
    )

    # Step 4 — apply features + reload env
    console.print("[cyan]→[/cyan] Applying feature matrix...")
    report = run_init(
        resolved_mode,
        hw,
        choices,
        dry_run=dry_run,
        progress=lambda m: console.print(f"[dim]{m}[/dim]"),
    )
    if not dry_run:
        from aria.config import reload_env

        reload_env()

    # Steps 5 & 6 — install binaries + download models
    voice_enabled = bool(choices.voice) and hw.has_nvidia_gpu
    installed = _install_binaries(resolved_mode, hw, voice_enabled, dry_run)
    downloaded = _download_models(resolved_mode, hw, voice_enabled, dry_run)

    # Step 7 — small-GPU warning (report.warning already carries it; reprint if set)
    if report.warning and not dry_run:
        console.print(f"[yellow]⚠ {report.warning}[/yellow]")

    # Step 8 — verify (preflight)
    _verify_preflight(dry_run)

    # Step 9 — summary
    _print_summary(report, installed, downloaded)

    # Sanity: the marker must exist after a real (non-dry-run) init.
    if not dry_run and not is_init_completed():
        error_console.print("[red]✗[/red] Init completed but marker missing")
        raise typer.Exit(1)
