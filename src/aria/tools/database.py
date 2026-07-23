"""Shared database engine for tool persistence.

Provides a singleton SQLAlchemy engine and session factory that all
tool database classes can use. This ensures a single connection pool
to the tools.db file.
"""

from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from aria.config.folders import DB

from .models import Base

_DEFAULT_DB_PATH = str(DB.path / "tools.db")


class ToolsDatabase:
    """Shared database engine for all tool modules."""

    _instance: "ToolsDatabase | None" = None
    _initialized: bool

    def __new__(cls, db_path: str = _DEFAULT_DB_PATH):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        if getattr(self, "_initialized", False):
            return

        self.db_path = db_path
        self._ensure_directory()
        self._setup_engine()
        self._initialized = True
        logger.info(f"ToolsDatabase initialized at {db_path}")

    def _ensure_directory(self) -> None:
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _setup_engine(self) -> None:
        database_url = f"sqlite:///{self.db_path}"
        self._engine = create_engine(database_url, echo=False, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        logger.debug(f"Tools database engine created: {database_url}")

    def create_tables(self) -> None:
        """Create all registered tool tables."""
        Base.metadata.create_all(self._engine)
        logger.debug("Tool database tables created/verified")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self._session_factory()

    def close(self) -> None:
        """Close database connections."""
        if self._engine:
            self._engine.dispose()
            logger.debug("Tools database connections closed")


def get_tools_database() -> ToolsDatabase:
    """Get the shared tools database singleton."""
    return ToolsDatabase()
