"""``aria.bootstrap`` — hardware detection, tier defaults, feature gating.

Public API:

- :func:`detect_hardware` — pure hardware detection (NVIDIA-only).
- :func:`resolve_defaults` — VRAM-tiered model defaults from
  ``models.json``.
- :func:`apply_mode_to_env` — write the feature matrix to ``.env``.
- :func:`run_init` — full orchestration used by ``aria init`` and reusable
  by the GUI wizard (returns an :class:`InitReport`).
- :func:`write_init_completed_marker` / :func:`is_init_completed` — the
  ``$ARIA_HOME/.init-completed.json`` gate the entry points check.

The GUI wizard reuses ``detect_hardware`` for its connection page; the
CLI ``aria init`` command drives ``run_init``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from aria.bootstrap.defaults import TierDefaults, resolve_defaults
from aria.bootstrap.detect import HardwareProfile, detect_hardware
from aria.bootstrap.features import (
    CHAT_MODE_LOCAL,
    CHAT_MODE_REMOTE,
    FeatureChoices,
    apply_mode_to_env,
    small_gpu_warning,
    vision_enabled_for_config,
)

ProgressFn = Callable[[str], None]

_MARKER_FILENAME = ".init-completed.json"


def _aria_home() -> Path:
    return Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))


def marker_path() -> Path:
    """Return the path to the ``.init-completed.json`` gate marker."""
    return _aria_home() / _MARKER_FILENAME


def is_init_completed() -> bool:
    """True when the ``aria init`` completion marker exists.

    The existing ``initializer.is_initialized()`` secret check only proves
    the ``.env`` bootstrap ran — not that binaries/models/mode were set up.
    Entry points gate on this marker instead (Decision 3).
    """
    return marker_path().is_file()


# Commands allowed before init completes (introspection / the init path
# itself). ``config paths`` is allowed so users can find ARIA_HOME when the
# marker is missing. Help-style invocation (no subcommand, or --help) is
# detected separately by the caller.
_INIT_EXEMPT_COMMANDS = frozenset({"init"})


def _is_help_invocation(argv: list[str]) -> bool:
    """True when the invocation asks for help at any level."""
    return "--help" in argv or "-h" in argv


def _is_config_paths(argv: list[str]) -> bool:
    """True for ``config paths`` — the "where is my ARIA_HOME?" escape hatch."""
    tokens = [t for t in argv if not t.startswith("-")]
    return len(tokens) >= 2 and tokens[0] == "config" and tokens[1] == "paths"


def _allowed_before_init(first_arg: str | None) -> bool:
    """True when *first_arg* is an init-exempt command path.

    Any ``--help``/``-h`` in the invocation is exempt (Typer renders
    group/subcommand help without needing setup). Also recognises compound
    paths like ``config paths`` (the second token is inspected) so users
    can locate ARIA_HOME without the marker.
    """
    import sys

    argv = sys.argv[1:]
    return (
        _is_help_invocation(argv)
        or first_arg is None  # bare invocation → help banner, never refuses
        or first_arg.startswith("-")  # global flag → Typer handles it
        or first_arg in _INIT_EXEMPT_COMMANDS
        or _is_config_paths(argv)
    )


def write_init_completed_marker(chat_mode: str, tier: TierDefaults | None) -> None:
    """Write the ``.init-completed.json`` marker at the end of a successful init.

    Records version, timestamp, chat mode, and the resolved tier so the
    entry-point gate passes for both the CLI and GUI front-ends.
    """
    from aria import __version__

    payload = {
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "chat_mode": chat_mode,
        "tier": {
            "chat_model": tier.chat_model if tier else None,
            "quant": tier.quant if tier else None,
            "context_size": tier.context_size if tier else None,
        },
    }
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass
class InitReport:
    """Outcome of a successful (or dry-run) ``aria init``.

    Attributes:
        chat_mode: The resolved chat mode (``"local"`` / ``"remote"``).
        hardware: The detected hardware profile.
        tier: The resolved tier defaults (``None`` in remote mode).
        changed_env_keys: ``.env`` keys that were written/changed.
        warning: Small-GPU VRAM-contention advisory, or ``None``.
        dry_run: True when no changes were actually written to disk.
    """

    chat_mode: str
    hardware: HardwareProfile
    tier: TierDefaults | None
    changed_env_keys: list[str] = field(default_factory=list)
    warning: str | None = None
    dry_run: bool = False


def _env_writable(env_path: Path) -> bool:
    """True when the ``.env`` file can be written (Docker ``:ro`` mount check)."""
    if not env_path.exists():
        return os.access(str(env_path.parent), os.W_OK)
    return os.access(str(env_path), os.W_OK)


def run_init(
    chat_mode: str,
    hardware: HardwareProfile,
    choices: FeatureChoices,
    *,
    dry_run: bool = False,
    progress: ProgressFn | None = None,
    write_marker: bool = True,
) -> InitReport:
    """Apply the feature matrix to ``.env`` + ``config.toml`` and return a report.

    This is the orchestrator shared by ``aria init`` and the GUI wizard's
    save step. It **only** handles feature application (plan step 4) +
    the small-GPU advisory (step 7); binary installs, model downloads,
    and preflight (steps 5/6/8) stay in the CLI flow because they need
    progress UI and are not idempotent no-ops the way env/config writes
    are. The completion marker is written by the caller on success — the
    CLI writes it after preflight passes; the GUI wizard writes it in its
    finalize step.

    A read-only ``.env`` (Docker ``:ro`` mount) is tolerated: the env
    write is skipped with a notice, process env vars are adopted as-is,
    and the ``config.toml`` sync still runs (it writes inside the writable
    ``/app/data`` volume).

    Args:
        chat_mode: ``"local"`` or ``"remote"``.
        hardware: Detected hardware profile.
        choices: User opt-ins (vision/voice/remote endpoint).
        dry_run: When True, compute the plan but write nothing.
        progress: Optional callback for human-facing progress lines.
        write_marker: Write the ``.init-completed.json`` marker at the end.
            The CLI passes ``False`` and writes the marker itself only
            after preflight succeeds, so a failed init never passes the
            entry-point gate.

    Returns:
        An :class:`InitReport` describing what was (or would be) applied.
    """

    def _say(msg: str) -> None:
        if progress is not None:
            progress(msg)

    env_path = _aria_home() / ".env"
    tier = resolve_defaults(hardware) if chat_mode == CHAT_MODE_LOCAL else None

    changed: list[str] = []
    if dry_run:
        _say("[dry-run] would apply feature matrix to .env + config.toml")
    elif not _env_writable(env_path):
        _say(".env is read-only (Docker mount) — adopting process env as-is")
    else:
        changed = apply_mode_to_env(env_path, chat_mode, hardware, choices, tier)
        if changed:
            _say(f"Updated .env: {', '.join(changed)}")

    # config.toml sync (writes inside the writable ARIA_HOME/.chainlit dir;
    # safe even when the .env mount is read-only).
    if not dry_run:
        from aria.server.manager import sync_chainlit_features

        vision = vision_enabled_for_config(hardware, chat_mode, choices)
        sync_chainlit_features(_aria_home(), vision_enabled=vision)
        _say("Synced .chainlit/config.toml features")

    # Voice value for the small-GPU warning: reflect what was just written
    # (or would be), honoring the no-GPU forced-false rule.
    voice_enabled = bool(choices.voice) and hardware.has_nvidia_gpu
    warning = small_gpu_warning(hardware, voice_enabled)
    if warning:
        _say(f"⚠ {warning}")

    if not dry_run and write_marker:
        write_init_completed_marker(chat_mode, tier)

    return InitReport(
        chat_mode=chat_mode,
        hardware=hardware,
        tier=tier,
        changed_env_keys=changed,
        warning=warning,
        dry_run=dry_run,
    )


__all__ = [
    "CHAT_MODE_LOCAL",
    "CHAT_MODE_REMOTE",
    "FeatureChoices",
    "HardwareProfile",
    "InitReport",
    "ProgressFn",
    "TierDefaults",
    "apply_mode_to_env",
    "detect_hardware",
    "is_init_completed",
    "marker_path",
    "resolve_defaults",
    "run_init",
    "small_gpu_warning",
    "vision_enabled_for_config",
    "write_init_completed_marker",
]
