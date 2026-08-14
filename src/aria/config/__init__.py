"""Configuration utilities for the Aria application.

Environment loading is lazy: the .env file is read on the first call to
``get_required_env()``, ``get_optional_env()``, or ``get_bool_env()`` —
**not** at import time.  This prevents import-time side effects and avoids
overriding monkeypatched env vars in tests.
"""

from os import getenv


class _EnvLoader:
    loaded = False


_loader = _EnvLoader()


def _ensure_env() -> None:
    """Load the .env file from ARIA_HOME on first use."""
    if _loader.loaded:
        return
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    env_path = aria_home / ".env"

    # Load from ARIA_HOME/.env if it exists
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Fallback: try CWD .env (backward compat)
        load_dotenv()

    _loader.loaded = True


def reload_env() -> None:
    """Force-reload the .env file from ARIA_HOME and refresh config classes.

    Call this after the wizard or GUI writes new values to .env so that
    subsequent ``get_*_env()`` calls and config attribute reads pick up
    the changes.  Re-executes the class bodies in ``config.api`` (whose
    attributes are evaluated once at import) and clears memoized
    ``_Lazy`` values in ``config.models``/``config.pdf``.
    """
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    aria_home = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria"))
    env_path = aria_home / ".env"

    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)

    _loader.loaded = True

    from aria.config import api, models, pdf
    from aria.config.api import _ENV_CLASS_BODIES
    from aria.config.folders import Bin, Knowledge, Models, Venvs

    exec_globals = {
        "get_optional_env": get_optional_env,
        "Path": Path,
        "Bin": Bin,
        "Knowledge": Knowledge,
        "Models": Models,
        "Venvs": Venvs,
    }
    for cls in (api.Vllm, api.KnowledgeHub, api.Lightpanda, api.Voice):
        namespace: dict = {}
        exec(  # noqa: S102 - re-evaluate env-derived attrs in a fresh namespace
            _ENV_CLASS_BODIES[cls.__name__],
            exec_globals,
            namespace,
        )
        for name, value in namespace.items():
            if not name.startswith("__"):
                setattr(cls, name, value)

    models.reset_lazy_config(models.Chat, models.Embeddings)
    models.reset_lazy_config(pdf.Pdf)


def get_bool_env(key: str, default: bool = False) -> bool:
    """Parse a boolean environment variable.

    Accepts common truthy strings: true, 1, yes, y, on (case-insensitive).
    """
    _ensure_env()
    value = getenv(key, None)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


DEBUG = get_bool_env("DEBUG", False)


def get_required_env(key: str) -> str:
    """Return the value of a required environment variable.

    Raises:
        ValueError: If the variable is not set.
    """
    _ensure_env()
    value = getenv(key, None)
    if value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value


def get_optional_env(key: str, default: str = "") -> str:
    """Return the value of an optional environment variable."""
    _ensure_env()
    return getenv(key, default)
