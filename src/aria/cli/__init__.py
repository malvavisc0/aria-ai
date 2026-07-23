"""CLI utilities for the Aria application.

This module provides shared utilities for CLI commands including:
- Database session management with automatic commit/rollback

Example:
    ```python
    from aria.cli import get_db_session

    with get_db_session() as session:
        # Perform database operations
        session.execute(text("SELECT 1"))
    ```
"""

import contextlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aria.config.database import SQLite
from aria.db.models import Base


class _EngineHolder:
    engine = None

    @classmethod
    def get(cls):
        """Lazily create the SQLAlchemy engine on first use.

        Deferring engine creation avoids opening the database at import time,
        which would fail if the database directory doesn't exist yet (e.g.
        during tests before fixtures run).
        """
        if cls.engine is None:
            from aria.config.folders import DB

            DB.path.mkdir(parents=True, exist_ok=True)
            cls.engine = create_engine(SQLite.db_url)
            Base.metadata.create_all(cls.engine)
        return cls.engine


@contextlib.contextmanager
def get_db_session():
    """Context manager for database sessions with automatic transaction handling.

    Uses a module-level singleton engine to avoid creating a new engine
    (and connection pool) on every invocation. Commits on success,
    rolls back on error, and always closes the session on exit.

    Yields:
        Session: An active SQLAlchemy session for database operations.

    Raises:
        Exception: Re-raises any exception that occurs during the session,
            after rolling back the transaction.

    Example:
        ```python
        with get_db_session() as session:
            users = session.execute(select(User)).scalars().all()
        ```
    """
    session = Session(_EngineHolder.get())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
