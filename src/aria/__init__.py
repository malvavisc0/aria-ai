__version__ = "0.4.1"


def _init_gate_should_pass() -> bool:
    """Return True when the invoked command may run before ``aria init``.

    Detection of the invoked command checks ``sys.argv[1]`` before Typer
    dispatch (Decision 3). ``init`` and ``config paths`` plus help-style
    introspection are exempt; everything else requires the completion
    marker so a fresh install doesn't half-start the server.
    """
    import sys

    from aria.bootstrap import _allowed_before_init, is_init_completed

    if is_init_completed():
        return True
    first = sys.argv[1] if len(sys.argv) > 1 else None
    return _allowed_before_init(first)


def main():
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    # Pre-load .env from CWD so ARIA_HOME and other vars are available
    # before initialization checks (supports Docker mounts at /app/.env).
    load_dotenv()

    # Pin ARIA_HOME as the working directory and tell Chainlit to use it
    # as APP_ROOT.  This MUST happen before any `import chainlit` because
    # chainlit.config evaluates APP_ROOT at module-import time via
    # os.getenv("CHAINLIT_APP_ROOT", os.getcwd()).
    aria_home = str(Path(os.environ.get("ARIA_HOME", Path.home() / ".aria")).resolve())
    os.environ.setdefault("CHAINLIT_APP_ROOT", aria_home)
    os.makedirs(aria_home, exist_ok=True)
    os.chdir(aria_home)

    from aria.initializer import (
        is_initialized,
        run_initialization,
        setup_chainlit_config,
        setup_public_assets,
    )

    if not is_initialized():
        run_initialization()

    # Idempotent — ensures assets exist even for already-initialized setups
    # (e.g. after upgrade or first run with new asset extraction logic).
    setup_public_assets()
    setup_chainlit_config()

    # Entry-point gate (Decision 3): refuse to run anything but `init` /
    # `config paths` / help until the init-completed marker exists.
    if not _init_gate_should_pass():
        sys.stderr.write("Aria is not set up yet. Run: aria init\n")
        sys.exit(1)

    from aria.cli.main import app

    app()


if __name__ == "__main__":
    main()
