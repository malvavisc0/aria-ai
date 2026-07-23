"""Pytest configuration and fixtures for aria tests."""

import atexit
import importlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Global test sandbox
#
# This MUST happen before any project module import so import-time path
# constants never resolve to the real ~/.aria tree.
# ---------------------------------------------------------------------------

_SESSION_SANDBOX = Path(tempfile.mkdtemp(prefix="aria-pytest-"))
_SESSION_ARIA_HOME = _SESSION_SANDBOX / "aria_home"
_SESSION_WORKSPACE = _SESSION_ARIA_HOME / "workspace"
_SESSION_ARIA_HOME.mkdir(parents=True, exist_ok=True)
_SESSION_WORKSPACE.mkdir(parents=True, exist_ok=True)

os.environ["ARIA_HOME"] = str(_SESSION_ARIA_HOME)
os.environ["CHAINLIT_APP_ROOT"] = str(_SESSION_ARIA_HOME)
os.environ["TOOLS_DATA_FOLDER"] = str(_SESSION_WORKSPACE)
os.environ.setdefault("SERVER_PORT", "9876")
os.environ.setdefault("ARIA_DB_FILENAME", "aria.db")
os.environ.setdefault("CHROMADB_PERSISTENT_PATH", "chromadb")
os.environ.setdefault("CHAT_OPENAI_API", "http://localhost:9090/v1")
os.environ.setdefault("MAX_ITERATIONS", "50")


@atexit.register
def _cleanup_session_sandbox() -> None:
    shutil.rmtree(_SESSION_SANDBOX, ignore_errors=True)


# Load environment variables from .env file, but keep the sandbox overrides.
load_dotenv()


# ---------------------------------------------------------------------------
# Pre-imported modules cache
#
# Importing modules is expensive (especially aria's large module tree).
# Cache the module objects once at collection time so the per-test
# autouse fixture only does cheap monkeypatch calls instead of
# repeated importlib.import_module + getattr lookups.
# ---------------------------------------------------------------------------

_CACHED_MODULES: dict[str, Any] = {}


def _get_cached_module(name: str):
    """Return a cached module import, importing lazily on first access."""
    mod = _CACHED_MODULES.get(name)
    if mod is None:
        try:
            mod = importlib.import_module(name)
            _CACHED_MODULES[name] = mod
        except ImportError:
            return None
    return mod


# Modules containing a DOWNLOADS_DIR binding that must be redirected in tests.
_DOWNLOADS_DIR_MODULES = (
    "aria.tools.constants",
    "aria.tools.search.constants",
    "aria.tools.search.download",
    "aria.tools.search.youtube",
)


@pytest.fixture(autouse=True)
def _isolate_data_dirs(tmp_path, monkeypatch):
    """Redirect all data directories to tmp_path so tests never touch production data/.

    Isolates:
    - Tool output directories (http, downloads)
    - Main SQLite database (aria.db)
    - ChromaDB path
    - Tools database (tools.db)
    - CLI engine (lazy — picks up patched paths)
    """
    http_dir = tmp_path / "http"
    http_dir.mkdir()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    monkeypatch.setattr("aria.tools.http.functions.HTTP_OUTPUT_DIR", http_dir)

    for mod_name in _DOWNLOADS_DIR_MODULES:
        mod = _get_cached_module(mod_name)
        if mod is not None and hasattr(mod, "DOWNLOADS_DIR"):
            monkeypatch.setattr(mod, "DOWNLOADS_DIR", downloads_dir)

    # ── Isolate ~/.aria root so tests never touch production data ──
    aria_home = tmp_path / "aria_home"
    aria_home.mkdir()
    monkeypatch.setenv("ARIA_HOME", str(aria_home))
    monkeypatch.setenv("TOOLS_DATA_FOLDER", str(aria_home / "workspace"))

    _folders = _get_cached_module("aria.config.folders")

    monkeypatch.setattr(_folders.Data, "path", aria_home)
    monkeypatch.setattr(_folders.Workspace, "path", aria_home / "workspace")
    monkeypatch.setattr(_folders.Bin, "path", aria_home / "bin")
    monkeypatch.setattr(_folders.Debug, "path", aria_home / "logs")
    monkeypatch.setattr(_folders.Debug, "logs_path", aria_home / "logs" / "debug.log")
    monkeypatch.setattr(_folders.Storage, "path", aria_home / "storage")
    monkeypatch.setattr(_folders.Uploads, "path", aria_home / "uploads")
    monkeypatch.setattr(_folders.DB, "path", aria_home / "db")
    monkeypatch.setattr(_folders.Models, "path", aria_home / "models")

    # ── Isolate workspace / BASE_DIR for file + shell tools ────
    workspace_dir = aria_home / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    _tools_const = _get_cached_module("aria.tools.constants")

    monkeypatch.setattr(_tools_const, "BASE_DIR", workspace_dir)

    # Derived directories that tools.constants creates at import time
    for attr in ("CODE_DIR", "DOWNLOADS_DIR", "REPORTS_DIR"):
        if hasattr(_tools_const, attr):
            d = workspace_dir / attr.replace("_DIR", "").lower()
            d.mkdir(exist_ok=True)
            monkeypatch.setattr(_tools_const, attr, d)

    _shell_const = _get_cached_module("aria.tools.shell.constants")

    monkeypatch.setattr(_shell_const, "BASE_DIR", workspace_dir)

    # Also patch BASE_DIR in modules that imported it via `from ... import`
    # (local bindings are not updated by patching the source module)
    _file_internals = _get_cached_module("aria.tools.files._internals")

    monkeypatch.setattr(_file_internals, "BASE_DIR", workspace_dir)

    _shell_valid = _get_cached_module("aria.tools.shell.validation")

    monkeypatch.setattr(_shell_valid, "BASE_DIR", workspace_dir)

    # ── Patch modules with import-time cached runtime paths ─────────
    process_state = aria_home / "processes.json"
    process_logs = aria_home / "logs" / "processes"
    process_logs.mkdir(parents=True, exist_ok=True)

    _process_funcs = _get_cached_module("aria.tools.process.functions")
    if _process_funcs is not None:
        monkeypatch.setattr(_process_funcs, "_STATE_FILE", process_state)
        monkeypatch.setattr(_process_funcs, "_LOG_DIR", process_logs)

        _test_process = _get_cached_module("aria.tools.process.tests.test_process")
        if _test_process is not None:
            monkeypatch.setattr(_test_process, "_STATE_FILE", process_state)

    _server_manager = _get_cached_module("aria.server.manager")
    if _server_manager is not None:
        monkeypatch.setattr(
            _server_manager.ServerManager,
            "PID_FILE",
            aria_home / "server.json",
        )

    _server_vllm = _get_cached_module("aria.server.vllm")
    if _server_vllm is not None:
        monkeypatch.setattr(
            _server_vllm.VllmServerManager,
            "PID_FILE",
            aria_home / "vllm_servers.json",
        )

    browser_dir = workspace_dir / "browser"
    browser_dir.mkdir(parents=True, exist_ok=True)

    _browser_constants = _get_cached_module("aria.tools.browser.constants")
    if _browser_constants is not None:
        monkeypatch.setattr(_browser_constants, "BROWSER_CONTENT_DIR", browser_dir)

    _browser_manager = _get_cached_module("aria.tools.browser.manager")
    if _browser_manager is not None:
        monkeypatch.setattr(_browser_manager, "BROWSER_CONTENT_DIR", browser_dir)

    # ── Isolate main database (SQLite + ChromaDB) ──────────────
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    _db_cfg = _get_cached_module("aria.config.database")

    monkeypatch.setattr(_db_cfg, "DB", type("DB", (), {"path": db_dir}))
    aria_db = db_dir / "aria.db"
    monkeypatch.setattr(_db_cfg, "_ARIA_DB_FILE_PATH", aria_db)
    monkeypatch.setattr(_db_cfg.SQLite, "file_path", aria_db)
    monkeypatch.setattr(_db_cfg.SQLite, "db_url", f"sqlite:///{aria_db}")
    monkeypatch.setattr(_db_cfg.SQLite, "conn_info", f"sqlite+aiosqlite:///{aria_db}")
    monkeypatch.setattr(_db_cfg.ChromaDB, "db_path", db_dir / "chromadb")

    # ── Isolate tools database default path ────────────────────
    _tools_db_mod = _get_cached_module("aria.tools.database")

    monkeypatch.setattr(_tools_db_mod, "_DEFAULT_DB_PATH", str(tmp_path / "tools.db"))

    # ── Reset CLI engine so it picks up the patched SQLite path ─
    _cli_mod = _get_cached_module("aria.cli")

    _cli_mod._engine = None


def _reset_all_db_singletons():
    """Reset all database singletons so the next call creates fresh ones."""
    from aria.tools.database import ToolsDatabase
    from aria.tools.knowledge.database import KnowledgeDatabase
    from aria.tools.planner.database import PlannerDatabase
    from aria.tools.reasoning.database import ReasoningDatabase
    from aria.tools.scratchpad.database import ScratchpadDatabase

    setattr(ToolsDatabase, "_instance", None)
    setattr(ReasoningDatabase, "_instance", None)
    setattr(PlannerDatabase, "_instance", None)
    setattr(ScratchpadDatabase, "_instance", None)
    setattr(KnowledgeDatabase, "_instance", None)


@pytest.fixture()
def test_tools_db(tmp_path):
    """Create a temporary ToolsDatabase for test isolation.

    This fixture resets all database singletons, creates a fresh
    ToolsDatabase pointing at a temp file, and registers it as the
    global instance so that downstream code (e.g. KnowledgeDatabase,
    ScratchpadDatabase) uses the same temp DB.
    The temp file is automatically deleted by pytest's ``tmp_path``.

    Usage in test modules::

        def test_something(test_tools_db):
            ...
    """
    from aria.tools.database import ToolsDatabase

    _reset_all_db_singletons()

    db_path = str(tmp_path / "test_tools.db")
    test_db = ToolsDatabase(db_path)
    test_db.create_tables()

    yield test_db

    test_db.close()
    _reset_all_db_singletons()
