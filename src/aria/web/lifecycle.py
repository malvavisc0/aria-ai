"""Application lifecycle handlers for the Aria web UI.

This module provides startup and shutdown handlers that are invoked
by Chainlit when the application starts and stops. It manages:
- Database initialization (SQLite, ChromaDB)
- LLM and embeddings model setup
- vLLM server management
- Browser automation (Lightpanda)
- Logging configuration
"""

from __future__ import annotations

import asyncio
import logging
import os

from chromadb import PersistentClient as ChromaDBPersistentClient
from loguru import logger
from sqlalchemy import create_engine

from aria.config.api import Vllm as VllmConfig
from aria.config.database import ChromaDB as ChromaDBConfig
from aria.config.database import SQLite as SQLiteConfig
from aria.config.folders import Data as DataConfig
from aria.config.folders import Debug as DebugConfig
from aria.config.models import Chat as ChatConfig
from aria.config.models import Embeddings as EmbeddingsConfig
from aria.llm import get_agent_workflow, get_chat_llm, get_embeddings_model
from aria.server.vllm import VllmServerManager
from aria.web.state import _state

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} - {level} - {name}.{function} : {message}"

_HEALTH_ENDPOINTS = ("/health",)


class _LogSinks:
    log_sink_id: int | None = None
    tool_call_sink_id: int | None = None


_sinks = _LogSinks()


class _HealthCheckFilter(logging.Filter):
    """Logging filter to suppress health check endpoint requests.

    Filters out noisy health check requests from uvicorn access logs
    to reduce log verbosity while still capturing other access logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(ep in msg for ep in _HEALTH_ENDPOINTS)


def _init_langfuse() -> None:
    """Initialize Langfuse instrumentation if env vars are present."""
    _langfuse_keys = (
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_BASE_URL",
    )
    if all(os.getenv(k) for k in _langfuse_keys):
        from langfuse import get_client
        from openinference.instrumentation.llama_index import (
            LlamaIndexInstrumentor,
        )

        get_client()
        LlamaIndexInstrumentor().instrument()
        logger.info("Langfuse instrumentation initialized")
    else:
        _missing = [k for k in _langfuse_keys if not os.getenv(k)]
        logger.warning(
            f"Langfuse instrumentation disabled — "
            f"missing env vars: {', '.join(_missing)}"
        )


def _init_logging() -> None:
    """Configure loguru file sinks and stdlib logger filters."""

    logger.remove()

    log_path = DebugConfig.logs_path
    # Always store INFO+ to avoid DEBUG log spam (WebSocket frames, etc.)
    _sinks.log_sink_id = logger.add(
        log_path,
        rotation="10 MB",
        level="INFO",  # Never store DEBUG to keep logs clean
        format=LOG_FORMAT,
    )

    # Dedicated sink for tool-call debug logs (keeps main log clean).
    # Filter uses the bound "tool_call" extra field set by log_tool_call
    # decorator — precise match instead of fragile string search.
    _sinks.tool_call_sink_id = logger.add(
        DebugConfig.logs_path.parent / "tools.log",
        rotation="10 MB",
        level="DEBUG",
        filter=lambda r: r["extra"].get("tool_call", False),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
    )
    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
    # Suppress WebSocket frame debug logs (TEXT/PING/PONG/keepalive spam)
    for _ws_logger_name in (
        "websockets",
        "uvicorn.protocol.websockets",
        "uvicorn.protocols.websockets",
    ):
        logging.getLogger(_ws_logger_name).setLevel(logging.WARNING)


def _init_storage_mount() -> None:
    """Mount the local storage directory as a static file server.

    Inserts a route at the START of Chainlit's router so that
    ``/storage/`` requests are served before the catch-all SPA
    route intercepts them and returns HTML.
    """
    from pathlib import PurePosixPath

    from chainlit.server import app
    from starlette.requests import Request
    from starlette.responses import FileResponse, Response
    from starlette.routing import Route

    from aria.config.folders import Storage as StorageConfig

    storage_dir = StorageConfig.path
    storage_dir.mkdir(parents=True, exist_ok=True)

    async def storage_endpoint(request: Request) -> Response:
        """Serve files from the local storage directory."""
        rel = request.path_params.get("file_path", "")
        safe = PurePosixPath("/", rel)
        file_path = storage_dir / str(safe).lstrip("/")
        if file_path.is_file():
            return FileResponse(str(file_path))
        from starlette.responses import JSONResponse

        return JSONResponse({"detail": "Not found"}, status_code=404)

    # Insert the storage route at the BEGINNING of the router
    # so it matches before Chainlit's catch-all SPA route.
    storage_route = Route(
        "/storage/{file_path:path}",
        endpoint=storage_endpoint,
        name="local-storage",
    )
    app.router.routes.insert(0, storage_route)

    logger.info(f"Mounted /storage route → {storage_dir}")


def _init_database() -> None:
    """Create the SQLite engine and ensure all tables exist."""
    from aria.db.models import Base

    _state.db_engine = create_engine(SQLiteConfig.db_url)
    Base.metadata.create_all(_state.db_engine)


def _is_chat_vllm_healthy(timeout: float = 2.0) -> bool:
    """Return True if the local vLLM chat server responds 200 on /health.

    Mirrors the local-mode branch of ``aria.cli.server._is_vllm_healthy``
    without pulling in Typer/CLI dependencies. Used by the web lifecycle
    to skip a redundant ``start_all()`` when the CLI already launched
    vLLM (otherwise ``start_all()``'s preflight port check would SIGTERM
    the healthy instance and reload the model from scratch).
    """
    from urllib.request import urlopen

    port = ChatConfig.get_port()
    try:
        with urlopen(f"http://localhost:{port}/health", timeout=timeout) as resp:
            return resp.status == 200
    except OSError:
        return False


def _init_vllm_servers() -> None:
    """Start all configured vLLM inference servers.

    If the chat vLLM server is already healthy on the configured port
    (e.g. started by the CLI before launching the web UI), adopt its
    tracked PIDs and skip ``start_all()``. This prevents the preflight
    port check from killing the healthy instance and reloading the
    model a second time (~12s of wasted work + log-file overwrite).
    """
    _state.vllm_manager = VllmServerManager()
    if _is_chat_vllm_healthy():
        logger.info(
            "vLLM chat server already healthy on port "
            f"{ChatConfig.get_port()} — adopting existing process, "
            "skipping redundant start_all()"
        )
        logger.info("All vLLM servers ready")
        return
    _state.vllm_manager.start_all()
    logger.info("All vLLM servers ready")


async def _probe_remote_vllm(api_url: str, timeout: float = 10.0) -> bool:
    """Best-effort health probe of a remote vLLM endpoint.

    Returns True if the endpoint responded (any HTTP status), False if the
    connection could not be established.  A non-200 is still considered
    "reachable" — the server is up even if still loading models.
    """
    import httpx

    health_url = api_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(health_url)
        logger.info(f"Remote vLLM endpoint reachable at {health_url}")
        return True
    except Exception as e:
        logger.warning(f"Remote vLLM health probe failed for {health_url}: {e}")
        return False


def _init_chat_llm() -> None:
    """Initialize the chat LLM client (requires vLLM to be healthy)."""
    _state.llm = get_chat_llm(
        api_base=ChatConfig.api_url,
        model=ChatConfig.model,
        api_key=VllmConfig.api_key,
    )


def _load_embeddings_sync() -> None:
    """Load the embeddings model in-process (CPU-only, no vLLM dependency).

    The embeddings model must be pre-downloaded to a local path (via
    ``aria models download --model embeddings``).  We fail fast when it is
    missing rather than silently falling back to a HuggingFace download,
    which on constrained devices can OOM or hang and stall startup
    indefinitely.
    """
    from pathlib import Path

    model_ref = EmbeddingsConfig.model_path or EmbeddingsConfig.model
    model_path = Path(model_ref) if model_ref else None

    if model_path and model_path.is_dir():
        resolved = str(model_path)
    else:
        raise RuntimeError(
            f"Embeddings model not found locally at '{model_ref}'. "
            "Pre-download it before starting the server: "
            "aria models download --model embeddings"
        )

    _state.embeddings = get_embeddings_model(model_name=resolved)


def _init_vector_db() -> None:
    """Initialize the ChromaDB persistent vector database.

    Validates the path is accessible before creating the client.
    If the database is corrupted (a ``ChromaError``), removes the
    directory and retries with a fresh instance.  Transient/non-corruption
    errors are **not** wiped — nuking the vector DB on any failure would
    destroy all threads' embeddings.
    """
    from chromadb.errors import ChromaError

    db_path = ChromaDBConfig.db_path
    db_path.mkdir(parents=True, exist_ok=True)

    # Verify the directory is writable
    test_file = db_path / ".aria_write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except OSError as e:
        raise RuntimeError(f"ChromaDB path '{db_path}' is not writable: {e}") from e

    try:
        _state.vector_db = ChromaDBPersistentClient(path=str(db_path))
    except ChromaError as e:
        logger.warning(
            f"ChromaDB corrupted ({e}). Resetting database at '{db_path}'..."
        )
        import shutil

        shutil.rmtree(db_path, ignore_errors=True)
        db_path.mkdir(parents=True, exist_ok=True)
        _state.vector_db = ChromaDBPersistentClient(path=str(db_path))
        logger.info("ChromaDB reset successfully with fresh database")


def _cleanup_orphaned_collections() -> None:
    """Remove ChromaDB collections for threads that no longer exist in SQLite.

    This prevents unbounded disk growth from deleted/expired conversations.
    Should be called after both the database and vector_db are initialized.
    """
    if _state.vector_db is None or _state.db_engine is None:
        return

    from sqlalchemy import text

    try:
        collections = _state.vector_db.list_collections()
        if not collections:
            return

        # Get all existing thread IDs from SQLite
        with _state.db_engine.connect() as conn:
            result = conn.execute(text("SELECT id FROM threads"))
            active_thread_ids = {row[0] for row in result}

        # Remove collections whose name isn't a known thread
        orphaned = [c.name for c in collections if c.name not in active_thread_ids]

        for name in orphaned:
            _state.vector_db.delete_collection(name)

        if orphaned:
            logger.info(f"Cleaned up {len(orphaned)} orphaned ChromaDB collections")
    except Exception as e:
        logger.warning(f"ChromaDB collection cleanup failed: {e}")


def _init_agent_workflows() -> None:
    """Create the agent workflow and prompt enhancer."""
    from aria.agents import get_prompt_enhancer_agent

    llm = _state.llm
    assert llm is not None
    _state.agents_workflow = get_agent_workflow(llm=llm)
    _state.prompt_enhancer = get_prompt_enhancer_agent(llm=llm)


async def _init_browser() -> None:
    """Start the Lightpanda browser if available."""
    from aria.config.api import Lightpanda

    if Lightpanda.is_available():
        from aria.tools.browser.manager import (
            LightpandaManager,
            set_browser_manager,
        )

        binary = Lightpanda.get_binary_path()
        if binary:
            browser_mgr = LightpandaManager(binary, port=Lightpanda.port)
            if await browser_mgr.start():
                _state.browser_manager = browser_mgr
                set_browser_manager(browser_mgr)
                logger.info("Lightpanda browser started successfully")
            else:
                logger.warning(
                    "Lightpanda browser failed to start — browser tools disabled"
                )
    else:
        logger.info("Lightpanda not installed — browser tools disabled")


async def _cleanup_on_failure() -> None:
    """Clean up partially initialized resources after startup failure.

    Mirrors the shutdown order in reverse so that resources are freed
    in the correct dependency order.
    """
    global _log_sink_id, _tool_call_sink_id

    if _state.browser_manager:
        try:
            await _state.browser_manager.stop()
        except Exception:
            pass
        _state.browser_manager = None

    if _state.vllm_manager:
        try:
            _state.vllm_manager.stop_all()
        except Exception:
            pass
        _state.vllm_manager = None

    if _state.db_engine:
        try:
            _state.db_engine.dispose()
        except Exception:
            pass
        _state.db_engine = None

    # Remove log sinks last so that cleanup logging above is captured.
    if _sinks.log_sink_id is not None:
        logger.remove(_sinks.log_sink_id)
        _sinks.log_sink_id = None
    if _sinks.tool_call_sink_id is not None:
        logger.remove(_sinks.tool_call_sink_id)
        _sinks.tool_call_sink_id = None


async def _abort_startup(exc: Exception, phase: str) -> None:
    """Clean up and terminate startup with a process-fatal exit."""
    DebugConfig.path.mkdir(parents=True, exist_ok=True)
    DebugConfig.startup_error_path.write_text(
        f"phase={phase}\nerror={exc}\n",
        encoding="utf-8",
    )
    logger.exception(f"Failed to start Aria web UI ({phase}): {exc}")
    await _cleanup_on_failure()
    raise SystemExit(1) from exc


async def _start_local_vllm_with_embeddings(embed_task) -> bool:
    try:
        logger.info("Starting vLLM inference servers...")
        await asyncio.to_thread(_init_vllm_servers)
        return True
    except Exception as e:
        await _cancel_embed_task(embed_task)
        await _abort_startup(e, "vLLM")
        return False


async def _start_remote_vllm_with_embeddings(embed_task) -> bool:
    logger.info(
        "Remote vLLM mode — skipping local server startup "
        f"(endpoint: {ChatConfig.api_url})"
    )
    if await _probe_remote_vllm(ChatConfig.api_url):
        return True
    await _cancel_embed_task(embed_task)
    await _abort_startup(
        RuntimeError(f"Remote vLLM endpoint not reachable at {ChatConfig.api_url}"),
        "vLLM",
    )
    return False


async def _cancel_embed_task(embed_task) -> None:
    embed_task.cancel()
    try:
        await embed_task
    except (asyncio.CancelledError, Exception):
        pass


async def _init_critical_infra() -> None:
    from chainlit.config import FILES_DIRECTORY

    FILES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    DebugConfig.path.mkdir(parents=True, exist_ok=True)
    DebugConfig.startup_error_path.unlink(missing_ok=True)

    _init_langfuse()
    _init_logging()
    logger.info("Starting Aria web UI...")

    _init_storage_mount()
    logger.info("Initializing database...")
    _init_database()


async def _finalize_subsystems(embed_task) -> None:
    try:
        await embed_task
        logger.info("Embeddings model loaded")
    except Exception as e:
        logger.warning(f"Embeddings model failed to load: {e}.")


async def on_app_startup_handler() -> None:
    """Initialize the application on startup.

    Called by Chainlit when the application starts. Orchestrates a
    sequence of initialization steps. Critical infrastructure
    (logging, storage, database, vLLM startup) failures are fatal and
    trigger a full rollback. Non-critical subsystems (vector database,
    browser) are best-effort.
    """
    # Phase 1 – Critical infrastructure
    try:
        await _init_critical_infra()
    except Exception as e:
        await _abort_startup(e, "critical")

    # Phase 2 – vLLM startup
    logger.info("Loading embeddings model (concurrent with vLLM)...")
    embed_task = asyncio.create_task(asyncio.to_thread(_load_embeddings_sync))

    if VllmConfig.remote:
        _vllm_ready = await _start_remote_vllm_with_embeddings(embed_task)
    else:
        _vllm_ready = await _start_local_vllm_with_embeddings(embed_task)

    # Phase 3 – Remaining subsystems
    await _finalize_subsystems(embed_task)

    _llm_ready = False
    if _vllm_ready:
        try:
            logger.info("Initializing chat LLM client...")
            _init_chat_llm()
            _llm_ready = True
        except Exception as e:
            logger.warning(f"Chat LLM client failed to initialize: {e}.")

    try:
        logger.info("Initializing vector database...")
        _init_vector_db()
    except Exception as e:
        logger.warning(f"Vector database failed to initialize: {e}.")

    _cleanup_orphaned_collections()

    if _llm_ready and _state.llm is not None:
        try:
            logger.info("Initializing agent workflows...")
            _init_agent_workflows()
        except Exception as e:
            logger.warning(f"Agent workflows failed to initialize: {e}.")

    try:
        await _init_browser()
    except Exception as e:
        logger.warning(f"Browser failed to start: {e}.")

    _state.startup_complete = True
    _state.startup_event.set()
    DebugConfig.startup_error_path.unlink(missing_ok=True)
    logger.info("Aria web UI startup complete")


def _consume_skip_vllm_sentinel() -> bool:
    sentinel = DataConfig.path / "skip_vllm_shutdown"
    if not sentinel.is_file():
        return False
    try:
        sentinel.unlink()
    except OSError:
        pass
    return True


def _stop_vllm_servers(skip_vllm: bool) -> None:
    if not _state.vllm_manager:
        return
    try:
        _state.vllm_manager.stop_all(skip_vllm=skip_vllm)
        if skip_vllm:
            logger.info("vLLM servers left running (--skip-vllm)")
        else:
            logger.info("All vLLM servers stopped")
    except Exception as e:
        logger.error(f"Error stopping vLLM servers: {e}")


async def _stop_browser() -> None:
    if not _state.browser_manager:
        return
    try:
        await _state.browser_manager.stop()
        logger.info("Lightpanda browser stopped")
    except Exception as e:
        logger.error(f"Error stopping Lightpanda browser: {e}")
    finally:
        from aria.tools.browser.manager import set_browser_manager

        set_browser_manager(None)
        _state.browser_manager = None


def _reset_app_state() -> None:
    _state.vllm_manager = None
    _state.llm = None
    _state.embeddings = None
    _state.vector_db = None
    _state.agents_workflow = None
    _state.prompt_enhancer = None
    _state.startup_complete = False
    _state.startup_event.clear()
    if _state.db_engine:
        _state.db_engine.dispose()
        _state.db_engine = None


def _remove_log_sinks() -> None:
    if _sinks.log_sink_id is not None:
        logger.remove(_sinks.log_sink_id)
        _sinks.log_sink_id = None
    if _sinks.tool_call_sink_id is not None:
        logger.remove(_sinks.tool_call_sink_id)
        _sinks.tool_call_sink_id = None


async def on_app_shutdown_handler() -> None:
    """Clean up resources on application shutdown.

    Called by Chainlit when the application is shutting down.
    Performs cleanup of:
    - vLLM inference servers
    - Lightpanda browser
    - Database connections
    - Data layer cache
    - Logging sinks
    """
    logger.info("Shutting down Aria web UI...")

    from aria.web.hooks import reset_data_layer_cache

    reset_data_layer_cache()
    _stop_vllm_servers(_consume_skip_vllm_sentinel())
    await _stop_browser()
    _reset_app_state()
    logger.info("Aria web UI shutdown complete")
    _remove_log_sinks()
