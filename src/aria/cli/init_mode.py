"""Chat-mode and feature-choice resolution for ``aria init``.

Everything that turns flags / env vars / interactive prompts into a
``(chat_mode, FeatureChoices)`` pair lives here so ``init.py`` stays a thin
command driver. The interactive prompts use Typer; the non-interactive and
dry-run paths are pure derivation.
"""

from __future__ import annotations

import os
import sys

import typer
from rich.console import Console

from aria.bootstrap import (
    CHAT_MODE_LOCAL,
    CHAT_MODE_REMOTE,
    FeatureChoices,
    HardwareProfile,
)

console = Console()


def _prompt_mode_interactive(hw: HardwareProfile) -> tuple[str, FeatureChoices]:
    """Interactive mode choice (default: local when GPU present).

    Returns ``(mode, choices)`` — a remote choice carries the prompted
    endpoint fields on *choices* (the step-4 writer persists them); a
    local choice carries an empty one.
    """
    if not hw.has_nvidia_gpu:
        console.print(
            "[red]No NVIDIA GPU detected — local chat is not available.[/red]"
        )
        return CHAT_MODE_REMOTE, _prompt_remote_endpoint_interactive()
    choice = (
        typer.prompt(
            "Chat mode",
            default="local",
            prompt_suffix=" [local/remote]: ",
        )
        .strip()
        .lower()
    )
    if choice == "local":
        return CHAT_MODE_LOCAL, FeatureChoices()
    if choice == "remote":
        return CHAT_MODE_REMOTE, _prompt_remote_endpoint_interactive()
    raise typer.BadParameter("mode must be 'local' or 'remote'")


def _prompt_remote_endpoint_interactive() -> FeatureChoices:
    """Prompt for remote endpoint fields and probe their reachability.

    The probe targets the prompted values directly (no ``os.environ``
    mutation, no ``reload_env()``) — fail fast at init, not at first
    server start. The values travel on the returned
    :class:`FeatureChoices` so the step-4 writer persists them.
    """
    from aria.server.lifecycle import _remote_endpoint_reachable

    url = typer.prompt("Remote endpoint URL (e.g. https://api.openai.com/v1)")
    api_key = typer.prompt("API key", hide_input=True)
    model = typer.prompt("Model name")
    result = _remote_endpoint_reachable(url=f"{url}/models", api_key=api_key)
    if not result.ok:
        raise typer.BadParameter(
            result.error or "Remote endpoint unreachable",
            param_hint="--remote-url / CHAT_OPENAI_API",
        )
    console.print("[green]✓[/green] Remote endpoint reachable")
    return FeatureChoices(remote_url=url, remote_api_key=api_key, remote_model=model)


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


def _validate_mode(mode: str | None, hw: HardwareProfile) -> None:
    """Validate an explicit --mode value (Decision 1: local needs NVIDIA)."""
    if mode is None:
        return
    if mode not in (CHAT_MODE_LOCAL, CHAT_MODE_REMOTE):
        raise typer.BadParameter("mode must be 'local' or 'remote'")
    if mode == CHAT_MODE_LOCAL and not hw.has_nvidia_gpu:
        # Same message as lifecycle._ensure_local_endpoint (Decision 1).
        raise typer.BadParameter(
            "No CUDA-capable GPU detected. Local vLLM requires NVIDIA CUDA "
            "drivers.\nSet ARIA_VLLM_REMOTE=true to connect to a remote "
            "OpenAI-compatible endpoint.",
        )


def _abort_no_gpu_no_mode(hw: HardwareProfile) -> None:
    """Refuse a non-interactive, no-GPU, no-mode run (Decision 1)."""
    if not hw.has_nvidia_gpu:
        raise typer.BadParameter(
            "No NVIDIA GPU and no --mode given (non-interactive context). "
            "Run with --mode remote, or set ARIA_VLLM_REMOTE=true.",
        )


def _resolve_dry_run_mode(hw: HardwareProfile) -> tuple[str, FeatureChoices]:
    """Dry-run without ``--mode``: derive like the non-interactive path.

    The would-abort case (no GPU, no remote env) prints the Decision-1
    outcome as the plan result and exits 0 — a dry run never exits
    non-zero.
    """
    remote = os.environ.get("ARIA_VLLM_REMOTE", "").strip().lower() == "true"
    if remote:
        return CHAT_MODE_REMOTE, FeatureChoices()
    if hw.has_nvidia_gpu:
        return CHAT_MODE_LOCAL, FeatureChoices()
    console.print(
        "[yellow]would abort:[/yellow] No NVIDIA GPU detected and "
        "ARIA_VLLM_REMOTE is not true — local chat requires NVIDIA CUDA. "
        "Set ARIA_VLLM_REMOTE=true and configure a remote "
        "OpenAI-compatible endpoint."
    )
    raise typer.Exit(0)


def _resolve_chat_mode(
    mode: str | None,
    hw: HardwareProfile,
    non_interactive: bool,
    dry_run: bool,
) -> tuple[str, FeatureChoices]:
    """Resolve the chat mode and its endpoint choices.

    Returns ``(mode, choices)``; the interactive remote prompt carries the
    prompted endpoint fields on *choices*, every other path an empty one.
    """
    _validate_mode(mode, hw)

    if non_interactive:
        return _resolve_mode_non_interactive(hw)
    if mode is not None:
        return mode, FeatureChoices()
    if not sys.stdin.isatty() and not dry_run:
        _abort_no_gpu_no_mode(hw)
    if dry_run:
        return _resolve_dry_run_mode(hw)
    return _prompt_mode_interactive(hw)


def _default_none_to_false(non_interactive: bool, choice: bool | None) -> bool | None:
    """In non-interactive mode, an unset choice defaults to False."""
    if non_interactive and choice is None:
        return False
    return choice


def _remote_endpoint_fields(
    url: str | None, api_key: str | None, model: str | None
) -> tuple[str, str, str]:
    """Resolve the remote endpoint fields — all-or-nothing.

    If any endpoint value is given (flag or prompted), all three are
    required: a partial set would silently mix given values with the
    stock template ones. When none are given the existing ``.env``
    values win (the never-overwrite contract in ``apply_mode_to_env``).
    """
    present = (url, api_key, model)
    if any(present) and not all(present):
        missing = [
            flag
            for flag, value in (
                ("--remote-url", url),
                ("--api-key", api_key),
                ("--model", model),
            )
            if not value
        ]
        raise typer.BadParameter(
            "Remote endpoint setup is all-or-nothing — missing: " + ", ".join(missing)
        )
    return url or "", api_key or "", model or ""


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
    remote_url_v, remote_key_v, remote_model_v = ("", "", "")
    if resolved_mode == CHAT_MODE_REMOTE:
        remote_url_v, remote_key_v, remote_model_v = _remote_endpoint_fields(
            remote_url, api_key, model
        )

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
