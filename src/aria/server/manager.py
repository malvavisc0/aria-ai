"""Server manager for controlling the Chainlit webserver lifecycle.

This module provides the ServerManager class for starting, stopping,
and monitoring the Aria Chainlit webserver process.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import aria
from aria.config.folders import Data as DataConfig
from aria.config.folders import Debug as DebugConfig
from aria.config.service import Server, is_loopback_host
from aria.server.process_utils import (
    clear_state,
    is_process_running,
    load_state,
    save_state,
    stop_process,
)

_AUDIO_ENABLED_RE = re.compile(
    r"\[features\.audio\]\n([^\[]*?)(enabled\s*=\s*)(true|false)",
    re.IGNORECASE,
)

# The packaged template's image MIME block — restored into the deployed
# config.toml ``accept`` array when vision is (re-)enabled. Kept in sync with
# ``src/aria/.chainlit/config.toml``'s ``[features.spontaneous_file_upload]``
# ``accept`` block; the round-trip test in bootstrap/tests pins this.
_TEMPLATE_IMAGE_MIMES = [
    '"image/png"',
    '"image/jpeg"',
    '"image/webp"',
    '"image/gif"',
    '"image/bmp"',
    '"image/tiff"',
]

# Matches the ``accept = [ ... ]`` array (DOTALL so newlines inside the
# array are spanned). The capture group is the full array body.
_ACCEPT_ARRAY_RE = re.compile(
    r"(\[features\.spontaneous_file_upload\]\n(?:[^\[]*?)accept\s*=\s*\[)"
    r"(.*?)"
    r"(\])",
    re.DOTALL,
)


def _sync_audio_feature(content: str, host: str) -> str:
    """Rewrite ``[features.audio] enabled`` for the loopback host rule.

    Audio is enabled only when voice is on (``ARIA_VLLM_VOICE_ENABLED``)
    and the bind is a loopback address (``getUserMedia`` needs a secure
    context). Any non-loopback bind or voice-disabled case turns it off so
    the broken mic button is not shown.
    """
    from aria.config.api import Voice

    enabled = Voice.enabled and is_loopback_host(host)
    value = "true" if enabled else "false"
    return _AUDIO_ENABLED_RE.sub(
        lambda m: f"[features.audio]\n{m.group(1)}{m.group(2)}{value}",
        content,
    )


def _sync_upload_accept(content: str, *, vision_enabled: bool) -> str:
    """Strip or restore ``image/*`` entries in the ``accept`` array.

    Image MIME types are only useful when vision is enabled. When vision
    is off, the contiguous image block is filtered out of the array; when
    on, the packaged template's image block is restored (idempotent if it
    is already present). On any parse surprise the section is left
    untouched — same fail-safe as the audio sync returning early on a
    missing file.
    """
    match = _ACCEPT_ARRAY_RE.search(content)
    if match is None:
        return content  # user reformat → leave untouched (fail-safe)

    head, body, tail = match.group(1), match.group(2), match.group(3)
    lines = body.splitlines()

    if not vision_enabled:
        kept = [ln for ln in lines if "image/" not in ln]
        new_body = "\n".join(kept)
    else:
        # Restore: drop any stray image lines first, then append the
        # template block once so re-enabling is idempotent.
        non_image = [ln for ln in lines if "image/" not in ln]
        restored = non_image + [f"    {mime}," for mime in _TEMPLATE_IMAGE_MIMES]
        new_body = "\n".join(restored)

    return content[: match.start()] + head + new_body + tail + content[match.end() :]


def sync_chainlit_features(
    aria_home: Path, *, host: str = "", vision_enabled: bool = False
) -> None:
    """Sync the deployed Chainlit config's feature flags in place.

    Two concerns, both regex-rewrite-in-place (never re-copy the file so
    user edits survive):

    - ``[features.spontaneous_file_upload] accept``: strip ``image/*``
      entries when *vision_enabled* is False, restore them from the
      packaged template list when True.
    - ``[features.audio] enabled``: enable only when voice is on and the
      bind is a loopback address. Skipped when *host* is empty (e.g. the
      init path, which runs before the server bind is known — the per-boot
      ``start()``/``run()`` call supplies the host).

    Run before launching the Chainlit subprocess so config reflects the
    current ``.env`` on every boot, and from ``aria init`` so the file
    matches the chosen mode immediately.

    Args:
        aria_home: ARIA_HOME, where ``.chainlit/config.toml`` lives.
        host: The bind address to evaluate the audio rule against. Empty
            skips the audio sync (used by the init path).
        vision_enabled: Whether ``image/*`` uploads should be kept.
    """
    config_path = aria_home / ".chainlit" / "config.toml"
    if not config_path.is_file():
        return

    content = config_path.read_text()
    updated = _sync_upload_accept(content, vision_enabled=vision_enabled)
    if host:
        updated = _sync_audio_feature(updated, host)
    if updated != content:
        config_path.write_text(updated)


def sync_chainlit_audio_feature(host: str, aria_home: Path) -> None:
    """Back-compat shim — delegates to :func:`sync_chainlit_features`.

    Kept so external callers and tests that reference the old name keep
    working. Prefer ``sync_chainlit_features`` for new call sites.
    """
    sync_chainlit_features(aria_home, host=host, vision_enabled=False)


def _vision_enabled() -> bool:
    """Read the current ``ARIA_VLLM_VISION_ENABLED`` flag from config.

    The config class is env-driven and re-evaluated on ``reload_env()``,
    so this reflects the latest ``.env`` state at every server start.
    """
    from aria.config.api import Vllm

    return bool(Vllm.vision_enabled)


@dataclass
class ServerStatus:
    """Status information for the webserver.

    Attributes:
        running: Whether the server process is alive.
        healthy: Whether the server is responding to HTTP requests on /health.
            This is False while Chainlit is still initializing (e.g. starting
            llama-server processes), and True once it is ready to serve.
        pid: Process ID of the running server, or None if not running.
        host: The host address the server is bound to.
        port: The port number the server is listening on.
        started_at: Timestamp when the server was started, or None.
        latency_ms: Round-trip time of the last /health check in milliseconds,
            or None if the server is not healthy.
    """

    running: bool
    healthy: bool
    pid: int | None
    host: str
    port: int
    started_at: datetime | None
    latency_ms: float | None = None

    @property
    def uptime_seconds(self) -> float | None:
        """Calculate uptime in seconds.

        Returns:
            Uptime in seconds, or None if the server is not running.
        """
        if self.started_at is None:
            return None
        return (datetime.now() - self.started_at).total_seconds()


class ServerManager:
    """Manages the Chainlit webserver lifecycle.

    This class provides methods to start, stop, restart, and monitor
    the Aria Chainlit webserver. It handles both development (uv) and
    installed package (pip) environments.

    Process state is persisted to a JSON file, allowing the manager
    to track servers started by other processes (e.g., CLI to GUI).

    Args:
        host: Host address to bind the server to. Defaults to Server.host.
        port: Port number to listen on. Defaults to Server.port.

    Attributes:
        pid: Process ID of the running server, or None if not running.
        started_at: Timestamp when the server was started, or None.
        uptime: Uptime in seconds, or None if not running.

    Example:
        ```python
        manager = ServerManager()

        # Start in background
        manager.start()
        print(f"Server PID: {manager.pid}")

        # Check status
        status = manager.get_status()
        print(f"Running: {status.running}, Uptime: {status.uptime_seconds}s")

        # Stop the server
        manager.stop()
        ```
    """

    PID_FILE = DataConfig.path / "server.json"

    @staticmethod
    def get_startup_error() -> str | None:
        """Return a captured startup error summary, if available."""
        path = DebugConfig.startup_error_path
        if not path.is_file():
            return None

        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

        if not content:
            return None

        parsed: dict[str, str] = {}
        for line in content.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                parsed[key.strip()] = value.strip()

        phase = parsed.get("phase")
        error = parsed.get("error")
        if phase and error:
            return f"{phase} startup failed: {error}"
        return content

    def __init__(self, host: str = Server.host, port: int = Server.port):
        """Initialize the ServerManager.

        Args:
            host: Host address to bind the server to. Defaults to Server.host.
            port: Port number to listen on. Defaults to Server.port.

        Reads host and port configuration from the Server config class,
        resolves the path to web_ui.py relative to the package location,
        and loads any existing process state from the PID file.
        """
        self._host = host
        self._port = port
        self._process: subprocess.Popen | None = None
        self._started_at: datetime | None = None

        # Resolve path to web_ui.py in the installed package
        package_dir = Path(aria.__file__).parent
        self._target = str(package_dir / "web_ui.py")

        # Load existing state from PID file
        self._load_state()

    def _load_state(self) -> None:
        """Load process state from the PID file.

        If the PID file exists and the process is still running,
        restores the _pid and _started_at from the saved state.
        If the saved PID is no longer running, clears all state.
        """
        state = load_state(self.PID_FILE)
        pid = state.get("pid")
        started_at_str = state.get("started_at")

        if pid and is_process_running(pid):
            self._pid = pid
            if started_at_str and isinstance(started_at_str, str):
                self._started_at = datetime.fromisoformat(started_at_str)
        else:
            self._pid = None
            self._started_at = None

    def _save_state(self) -> None:
        """Save process state to the PID file."""
        data = {
            "pid": self.pid,
            "host": self._host,
            "port": self._port,
            "started_at": (self._started_at.isoformat() if self._started_at else None),
        }
        save_state(self.PID_FILE, data)

    def _clear_state(self) -> None:
        """Clear the PID file and reset all in-memory state."""
        self._pid = None
        self._process = None
        self._started_at = None
        clear_state(self.PID_FILE)

    @property
    def host(self) -> str:
        """The host address the server is bound to."""
        return self._host

    @property
    def port(self) -> int:
        """The port number the server is listening on."""
        return self._port

    @property
    def pid(self) -> int | None:
        """Get the process ID of the running server.

        Returns:
            Process ID, or None if the server is not running.
        """
        if self._process is not None:
            return self._process.pid
        return getattr(self, "_pid", None)

    @property
    def started_at(self) -> datetime | None:
        """Get the time when the server was started.

        Returns:
            Start timestamp, or None if the server is not running.
        """
        return self._started_at

    def _build_command(self) -> list[str]:
        """Build the chainlit run command.

        Always invokes ``chainlit`` directly (found via the augmented
        ``PATH`` set by :func:`get_augmented_env`).  Both the subprocess
        CWD (via :meth:`_resolve_cwd`) and the ``CHAINLIT_APP_ROOT``
        env var are set to ARIA_HOME so that Chainlit discovers
        ``public/``, ``.chainlit/``, and ``chainlit.md`` there — never
        in the caller's CWD.  The env var is the authoritative
        override because ``uv run`` can reset the OS-level CWD before
        the Python interpreter starts importing modules.

        Note: ``--root-path`` is intentionally omitted. It is a URL
        path prefix for reverse-proxy deployments, not a filesystem
        path.

        Returns:
            List of command arguments for subprocess.
        """
        return [
            "chainlit",
            "run",
            "--no-cache",
            "--host",
            self._host or "0.0.0.0",
            "--port",
            str(self._port),
            self._target,
        ]

    def _resolve_cwd(self) -> str:
        """Return ARIA_HOME as the CWD for the Chainlit subprocess.

        Chainlit resolves ``public/``, ``.chainlit/``, and
        ``chainlit.md`` relative to its CWD.  Running from ARIA_HOME
        ensures these assets (extracted during initialization) are
        always found, regardless of where the CLI was invoked.
        """
        return str(DataConfig.path)

    def start(self) -> bool:
        """Start the webserver as a background subprocess.

        Stdout and stderr are appended to the application log file so that
        Chainlit output is visible in the Logs tab and pipe-buffer deadlocks
        are avoided (a PIPE that is never read will block the child process
        once the OS buffer fills up).

        The log file handle is opened without ``with`` so it remains open
        for the lifetime of the subprocess (the OS will close it when the
        child exits).

        Returns:
            True if the server was started successfully,
            False if the server is already running.
        """
        if self.is_running():
            return False

        from aria.config.folders import Debug as DebugConfig

        log_path = DebugConfig.logs_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        aria_home = self._resolve_cwd()
        os.chdir(aria_home)
        sync_chainlit_features(
            Path(aria_home), host=self._host, vision_enabled=_vision_enabled()
        )

        cmd = self._build_command()
        log_file = open(log_path, "a")
        from aria.config.folders import get_augmented_env

        env = get_augmented_env()
        env["DEBUG"] = "false"
        env["CHAINLIT_APP_ROOT"] = aria_home
        self._process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            env=env,
            cwd=aria_home,
        )
        log_file.close()  # safe: the OS dup'd the fd into the child process
        self._started_at = datetime.now()
        self._save_state()
        return True

    def run(self) -> None:
        """Run the webserver in the foreground (blocking).

        This method blocks until the server is stopped (Ctrl+C).
        Does nothing if the server is already running.
        """
        if self.is_running():
            return

        aria_home = self._resolve_cwd()
        os.chdir(aria_home)
        sync_chainlit_features(
            Path(aria_home), host=self._host, vision_enabled=_vision_enabled()
        )

        cmd = self._build_command()
        log_path = DebugConfig.logs_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._started_at = datetime.now()
        self._save_state()
        log_file = open(log_path, "a")  # noqa: WPS515 — kept open for subprocess lifetime
        try:
            from aria.config.folders import get_augmented_env

            env = get_augmented_env()
            env["DEBUG"] = "false"
            env["CHAINLIT_APP_ROOT"] = aria_home
            result = subprocess.run(
                cmd,
                env=env,
                stdout=log_file,
                stderr=log_file,
                cwd=aria_home,
            )
            if result.returncode != 0:
                startup_error = self.get_startup_error()
                if startup_error:
                    raise RuntimeError(startup_error)
                raise RuntimeError(f"Web UI exited with status {result.returncode}")
        finally:
            log_file.close()
            self._clear_state()

    def stop(self, timeout: float = 10.0) -> bool:
        """Stop the running webserver.

        Sends SIGTERM to the process, then SIGKILL if it doesn't
        terminate within the timeout period.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown.

        Returns:
            True if the server was stopped successfully,
            False if the server was not running.
        """
        if not self.is_running():
            return False

        pid = self.pid
        if pid is None:
            return False

        # If we have a Popen object, use it
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        else:
            # Otherwise, kill by PID using shared utility
            stop_process(pid, timeout)

        self._clear_state()
        return True

    def is_running(self) -> bool:
        """Check if the server process is alive.

        Returns:
            True if the server process is alive, False otherwise.
        """
        # Check if we have an active Popen object
        if self._process is not None:
            return self._process.poll() is None

        # Check if there's a running process from the PID file
        pid = getattr(self, "_pid", None)
        if pid is not None:
            return is_process_running(pid)

        return False

    def _check_health(self) -> tuple[bool, float | None]:
        """Check health and measure round-trip latency.

        Returns:
            A tuple of (healthy, latency_ms). ``latency_ms`` is the
            round-trip time in milliseconds, or None if the check failed.
        """
        import time

        try:
            host = self._host or "127.0.0.1"
            url = f"http://{host}:{self._port}/health"
            start = time.monotonic()
            with urlopen(url, timeout=1) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                return resp.status == 200, elapsed_ms
        except (URLError, OSError):
            return False, None

    def get_status(self) -> ServerStatus:
        """Get detailed server status.

        Also clears stale in-memory state if the process has died
        unexpectedly (i.e. without an explicit ``stop()`` call), so that
        uptime and PID labels reset correctly in the GUI.

        Returns:
            ServerStatus dataclass with current server information.
        """
        running = self.is_running()
        if not running and (self._process is not None or self._started_at is not None):
            # Process died on its own — clear stale state so labels reset
            self._clear_state()

        healthy, latency_ms = self._check_health() if running else (False, None)
        return ServerStatus(
            running=running,
            healthy=healthy,
            pid=self.pid,
            host=self._host,
            port=self._port,
            started_at=self._started_at,
            latency_ms=latency_ms,
        )
