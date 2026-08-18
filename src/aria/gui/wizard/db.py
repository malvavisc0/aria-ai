"""Database-backed helpers for the setup wizard."""

from __future__ import annotations

from pathlib import Path


def _has_admin_user() -> bool:
    """Return True if at least one user exists in the database.

    Errors propagate to the caller: silently returning False for a
    corrupt database would loop the first-run wizard indefinitely.
    """
    from sqlalchemy import select

    from aria.cli import get_db_session
    from aria.db.models import User

    with get_db_session() as session:
        users = session.execute(select(User)).scalars().all()
        return len(users) > 0


def _is_model_downloaded(model_path: str) -> bool:
    """Check if a model directory exists and is non-empty."""
    path = Path(model_path)
    return path.exists() and any(path.iterdir())
