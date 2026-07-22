"""First-run initialization for Aria CLI and GUI.

Creates required files and directories on first launch:
- .env file with generated CHAINLIT_AUTH_SECRET
- Data, storage, and chromadb directories
- SQLite database with tables
- Log file
"""

import secrets
from importlib.resources import as_file, files
from pathlib import Path
from shutil import copyfile

from rich.console import Console

from aria.helpers.network import get_network_ip

console = Console()


def _get_aria_home() -> Path:
    """Return the ARIA_HOME directory (defaults to ~/.aria)."""
    import os

    return Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))


def _has_valid_secret(value: str) -> bool:
    """Return True if the secret is non-empty and not a placeholder."""
    return bool(value) and value not in ("your-secret-here", "changeme")


def is_initialized() -> bool:
    """Check if the environment is already initialized.

    Returns True when a valid CHAINLIT_AUTH_SECRET is available — either
    already loaded into ``os.environ`` (e.g. Docker with a mounted .env)
    or present inside the ARIA_HOME ``.env`` file.

    When the secret is found only in the ARIA_HOME ``.env`` file (e.g. a
    Docker restart where the mounted ``.env`` left it blank but a previous
    boot persisted it), it is also populated into ``os.environ`` so that
    downstream consumers (Chainlit session signing) see it without a separate
    ``load_dotenv`` pass.
    """
    import os

    # Fast path: secret already in the environment (Docker / pre-loaded).
    env_secret = os.environ.get("CHAINLIT_AUTH_SECRET", "").strip()
    if _has_valid_secret(env_secret):
        return True

    # Fallback: check the ARIA_HOME .env file directly.
    env_file = _get_aria_home() / ".env"
    if not env_file.exists():
        return False

    content = env_file.read_text()
    for line in content.splitlines():
        if line.startswith("CHAINLIT_AUTH_SECRET"):
            if "=" in line:
                value = line.split("=", 1)[1].strip()
                if _has_valid_secret(value):
                    # Populate env so Chainlit and other consumers see the
                    # persisted secret on every boot, not just the first.
                    os.environ["CHAINLIT_AUTH_SECRET"] = value
                    return True
    return False


def generate_secret() -> str:
    """Generate a secure random secret for CHAINLIT_AUTH_SECRET."""
    return secrets.token_urlsafe(32)


def setup_env_file() -> bool:
    """Create .env from .env.example with generated secret and network IP.

    Creates the .env file in ARIA_HOME (defaults to ~/.aria).
    If a .env was already loaded into the environment (Docker mount),
    generates a missing CHAINLIT_AUTH_SECRET and persists it to the
    ARIA_HOME .env file (the mounted config is typically read-only) so
    the secret survives container restarts.
    """
    import os

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    aria_home.mkdir(parents=True, exist_ok=True)
    env_file = aria_home / ".env"

    if env_file.exists():
        return False

    # Docker / pre-loaded path: env vars are set but no .env in ARIA_HOME.
    # Generate a secret and persist it to the ARIA_HOME .env file so it
    # survives container restarts (the mounted /app/.env is read-only and
    # may leave CHAINLIT_AUTH_SECRET blank).  is_initialized() reloads it
    # into os.environ on subsequent boots.
    if os.environ.get("CHAT_MODEL") or os.environ.get("CHAT_OPENAI_API"):
        if not _has_valid_secret(os.environ.get("CHAINLIT_AUTH_SECRET", "").strip()):
            secret = generate_secret()
            os.environ["CHAINLIT_AUTH_SECRET"] = secret
            env_file.write_text(f"CHAINLIT_AUTH_SECRET = {secret}\n")
            env_file.chmod(0o600)
            console.print(
                "   [green]✓[/green] Auto-generated and persisted CHAINLIT_AUTH_SECRET"
            )
        console.print("   [green]✓[/green] Using pre-loaded configuration")
        return True

    # Standard path: copy .env.example into ARIA_HOME.
    env_example_ref = files("aria").joinpath(".env.example")
    with as_file(env_example_ref) as env_example:
        copyfile(env_example, env_file)

    secret = generate_secret()
    content = env_file.read_text()
    content = content.replace(
        "CHAINLIT_AUTH_SECRET =", f"CHAINLIT_AUTH_SECRET = {secret}"
    )

    # Detect and set network IP for SERVER_HOST
    network_ip = get_network_ip()
    content = content.replace(
        "SERVER_HOST = 0.0.0.0",
        f"SERVER_HOST = {network_ip}",
    )

    env_file.write_text(content)
    env_file.chmod(0o600)

    console.print("   [green]✓[/green] Created .env configuration")
    console.print("   [green]✓[/green] Generated CHAINLIT_AUTH_SECRET")
    console.print(f"   [green]✓[/green] Detected network IP: {network_ip}")
    return True


def setup_directories() -> None:
    """Create required directories."""
    from dotenv import load_dotenv

    load_dotenv()

    from aria.config.database import ChromaDB
    from aria.config.folders import (
        DB,
        Bin,
        Data,
        Debug,
        Models,
        Storage,
        Workspace,
    )

    Data.path.mkdir(parents=True, exist_ok=True)
    Workspace.path.mkdir(parents=True, exist_ok=True)
    Bin.path.mkdir(parents=True, exist_ok=True)
    Debug.path.mkdir(parents=True, exist_ok=True)
    Storage.path.mkdir(parents=True, exist_ok=True)
    DB.path.mkdir(parents=True, exist_ok=True)
    Models.path.mkdir(parents=True, exist_ok=True)
    ChromaDB.db_path.mkdir(parents=True, exist_ok=True)
    console.print("   [green]✓[/green] Created data directories")
    console.print("   [green]✓[/green] Created chromadb directory")


def setup_database() -> None:
    """Create SQLite database and all tables."""
    from sqlalchemy import create_engine

    from aria.config.database import SQLite
    from aria.db.models import Base

    engine = create_engine(SQLite.db_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    console.print("   [green]✓[/green] Initialized database")


def setup_public_assets() -> None:
    """Copy public/ assets (CSS, logos, theme) from the package to ARIA_HOME.

    Chainlit expects a ``public/`` directory in its CWD. When running
    from a pip-installed package (e.g. Docker), these files aren't present
    in the filesystem — they live inside the installed package. This
    function extracts them once into ARIA_HOME so Chainlit can find them.
    """
    import os
    from shutil import copy2

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    public_dest = aria_home / "public"

    if public_dest.exists():
        return

    public_ref = files("aria").joinpath("public")
    with as_file(public_ref) as public_src:
        if not public_src.is_dir():
            return

        public_dest.mkdir(parents=True, exist_ok=True)
        for item in public_src.iterdir():
            if item.is_dir():
                sub_dest = public_dest / item.name
                sub_dest.mkdir(exist_ok=True)
                for child in item.iterdir():
                    copy2(child, sub_dest / child.name)
            else:
                copy2(item, public_dest / item.name)

    console.print("   [green]✓[/green] Installed public assets (CSS, logos)")


def setup_logs() -> None:
    """Create log file if it doesn't exist."""
    from aria.config.folders import Debug

    if not Debug.logs_path.exists():
        Debug.logs_path.parent.mkdir(parents=True, exist_ok=True)
        Debug.logs_path.touch()
    console.print("   [green]✓[/green] Created log file")


def setup_chainlit_config() -> None:
    """Copy .chainlit/ (config + translations) and chainlit.md to ARIA_HOME.

    Chainlit expects these files in its CWD.  When running from a
    pip-installed package (e.g. Docker), they live inside the installed
    package and must be extracted once into ARIA_HOME.
    """
    import os
    from shutil import copy2

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    chainlit_dest = aria_home / ".chainlit"
    config_dest = chainlit_dest / "config.toml"
    trans_dest = chainlit_dest / "translations"
    md_dest = aria_home / "chainlit.md"

    # Skip if everything is already in place.
    if config_dest.exists() and trans_dest.exists() and md_dest.exists():
        return

    # ── .chainlit/config.toml ────────────────────────────────────────
    if not config_dest.exists():
        config_ref = files("aria").joinpath(".chainlit", "config.toml")
        with as_file(config_ref) as config_src:
            if config_src.is_file():
                chainlit_dest.mkdir(parents=True, exist_ok=True)
                copy2(config_src, config_dest)

    # ── .chainlit/translations/*.json ────────────────────────────────
    if not trans_dest.exists():
        trans_ref = files("aria").joinpath(".chainlit", "translations")
        with as_file(trans_ref) as trans_src:
            if trans_src.is_dir():
                trans_dest.mkdir(parents=True, exist_ok=True)
                for json_file in trans_src.iterdir():
                    if json_file.suffix == ".json":
                        copy2(json_file, trans_dest / json_file.name)

    # ── chainlit.md (welcome message) ────────────────────────────────
    if not md_dest.exists():
        md_ref = files("aria").joinpath("chainlit.md")
        with as_file(md_ref) as md_src:
            if md_src.is_file():
                copy2(md_src, md_dest)

    console.print(
        "   [green]✓[/green] Installed Chainlit config, translations, and welcome page"
    )


def run_initialization() -> None:
    """Run all initialization steps for first-time setup."""
    console.print("🔧 [bold]First-time setup...[/bold]")
    setup_env_file()
    setup_directories()
    setup_database()
    setup_logs()
    setup_public_assets()
    setup_chainlit_config()
    console.print()
