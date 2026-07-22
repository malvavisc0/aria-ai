__version__ = "0.3.2"


def main():
    import os
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

    from aria.cli.main import app

    app()


if __name__ == "__main__":
    main()
