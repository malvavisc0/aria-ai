"""Shared server lifecycle orchestration for the CLI and GUI.

Keeps the Chainlit + vLLM startup and shutdown control flow in one place
so ``aria.cli.server`` and ``aria.gui.windows.server_handlers`` cannot
drift apart.  Presentation (Rich console output, Qt status-bar messages)
is left to callers via an optional ``progress`` callback; this module
only orchestrates and reports structured results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

ProgressFn = Callable[[str], None]

_HEALTH_POLL_INTERVAL = 0.5
_VLLM_HEALTH_TIMEOUT = 120


@dataclass
class StepResult:
    """Outcome of a lifecycle step (endpoint check, vLLM start, ...)."""

    ok: bool
    error: str | None = None


@dataclass
class StopResult:
    """Outcome of a full server stop (web UI + vLLM)."""

    web_stopped: bool
    vllm_skipped: bool
    vllm_had_pids: bool


def has_cuda() -> bool:
    """Return True if a CUDA-capable GPU is available."""
    try:
        from aria.helpers.nvidia import get_total_vram_mb

        return get_total_vram_mb() > 0
    except Exception:
        return False


def _authenticated_get(url: str, timeout: float = 5):
    """Open *url* carrying the vLLM API key when in remote mode."""
    from aria.config.api import Vllm as VllmConfig

    headers = {}
    if VllmConfig.remote and VllmConfig.api_key:
        headers["Authorization"] = f"Bearer {VllmConfig.api_key}"
    return urlopen(Request(url, headers=headers), timeout=timeout)


def is_vllm_healthy() -> bool:
    """Return True if the vLLM chat endpoint is responding.

    Remote mode probes the configured ``Chat.api_url``; local mode probes
    ``localhost:<chat port>/health``.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.models import Chat

    if VllmConfig.remote:
        try:
            with _authenticated_get(f"{Chat.api_url}/models", timeout=5) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    port = Chat.get_port()
    try:
        with urlopen(f"http://localhost:{port}/health", timeout=2) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def _remote_endpoint_reachable(timeout: float = 10.0) -> StepResult:
    from aria.config.models import Chat

    try:
        with _authenticated_get(f"{Chat.api_url}/models", timeout=timeout) as resp:
            if resp.status == 200:
                return StepResult(ok=True)
            return StepResult(
                ok=False, error=f"Remote endpoint returned HTTP {resp.status}"
            )
    except (URLError, OSError) as e:
        return StepResult(
            ok=False, error=f"Remote endpoint unreachable: {Chat.api_url}\n  {e}"
        )


def _ensure_local_endpoint(progress: ProgressFn | None = None) -> StepResult:
    """Local-mode endpoint bring-up: require CUDA, start vLLM if unhealthy."""
    if not has_cuda():
        return StepResult(
            ok=False,
            error=(
                "No CUDA-capable GPU detected. Local vLLM requires NVIDIA CUDA "
                "drivers.\nSet ARIA_VLLM_REMOTE=true to connect to a remote "
                "OpenAI-compatible endpoint."
            ),
        )

    if is_vllm_healthy():
        if progress:
            progress("OpenAI endpoint already running")
        return StepResult(ok=True)

    if progress:
        progress("Starting vLLM server\u2026")
    try:
        from aria.server.vllm import VllmServerManager

        VllmServerManager().start_all()
    except Exception as e:
        from aria.server.manager import ServerManager

        captured = ServerManager.get_startup_error()
        return StepResult(ok=False, error=captured or f"Failed to start vLLM: {e}")

    if progress:
        progress("OpenAI endpoint healthy")
    return StepResult(ok=True)


def ensure_endpoint_reachable(progress: ProgressFn | None = None) -> StepResult:
    """Ensure the OpenAI-compatible endpoint is reachable before serving.

    Remote mode: validate the configured endpoint (fail-fast).
    Local mode: require CUDA, start vLLM if unhealthy, wait for health.

    The web UI adopts an already-healthy vLLM instead of restarting it
    (see ``aria.web.lifecycle._init_vllm_servers``), so starting vLLM here
    is the supported pattern — the same one the CLI uses.
    """
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        result = _remote_endpoint_reachable()
        if result.ok and progress:
            progress("Remote OpenAI endpoint reachable")
        return result

    return _ensure_local_endpoint(progress)


def ensure_vllm_running(progress: ProgressFn | None = None) -> StepResult:
    """Start vLLM if not already running (safety net after web UI startup).

    Remote mode: verify the remote endpoint is reachable.
    Local mode: if vLLM is already healthy, adopt it; otherwise start it.
    """
    from aria.config.api import Vllm as VllmConfig

    if VllmConfig.remote:
        if is_vllm_healthy():
            return StepResult(ok=True)
        from aria.config.models import Chat

        return StepResult(
            ok=False, error=f"Remote vLLM endpoint not reachable: {Chat.api_url}"
        )

    if is_vllm_healthy():
        return StepResult(ok=True)

    if progress:
        progress("vLLM not running — starting\u2026")
    try:
        from aria.server.vllm import VllmServerManager

        VllmServerManager().start_all()
        return StepResult(ok=True)
    except Exception as e:
        from aria.server.manager import ServerManager

        captured = ServerManager.get_startup_error()
        return StepResult(ok=False, error=captured or f"Failed to start vLLM: {e}")


def wait_for_web_health(
    host: str,
    port: int,
    timeout: float,
    *,
    process_alive: Callable[[], bool] | None = None,
) -> bool:
    """Poll ``/health`` until the web UI returns 200 or *timeout* elapses.

    Exits early if ``process_alive`` reports the subprocess has died.
    """
    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process_alive is not None and not process_alive():
            return False
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (URLError, OSError):
            pass
        time.sleep(_HEALTH_POLL_INTERVAL)
    return False


def stop_server(
    skip_vllm: bool = False, progress: ProgressFn | None = None
) -> StopResult:
    """Stop the web UI, then vLLM (with orphan cleanup).

    Snapshots vLLM PIDs before stopping the web UI because the Chainlit
    shutdown hook may clear the PID file during teardown. Always
    attempts to stop vLLM — even if the web server was already dead, vLLM
    may survive as an orphan.
    """
    from aria.config.api import Vllm as VllmConfig
    from aria.config.folders import Data as DataConfig
    from aria.server.manager import ServerManager
    from aria.server.vllm import VllmServerManager

    if skip_vllm:
        (DataConfig.path / "skip_vllm_shutdown").touch()

    vllm_pids: dict[str, int] = {}
    if not skip_vllm:
        vllm_pids = VllmServerManager()._pids.copy()

    manager = ServerManager()
    web_stopped = manager.stop()

    if not skip_vllm and not VllmConfig.remote:
        if progress:
            progress("Stopping vLLM servers…")
        vllm = VllmServerManager()
        live_pids = {**vllm_pids, **vllm._pids}
        if live_pids:
            vllm._pids = live_pids
        vllm.stop_all()

    return StopResult(
        web_stopped=web_stopped,
        vllm_skipped=skip_vllm,
        vllm_had_pids=bool(vllm_pids),
    )
