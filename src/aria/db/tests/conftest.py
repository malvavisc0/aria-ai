"""Shared fixtures and utilities for SQLite data layer tests."""

import uuid
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aria.db.layer import SQLiteSQLAlchemyDataLayer
from aria.db.models import Base


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database file path.

    Args:
        tmp_path: pytest's temporary directory fixture

    Returns:
        Path to temporary SQLite database file
    """
    return tmp_path / "test_chainlit.db"


@pytest_asyncio.fixture
async def db_engine(temp_db_path: Path) -> AsyncGenerator[AsyncEngine, None]:
    """Create a SQLite database engine with schema.

    Args:
        temp_db_path: Path to temporary database file

    Yields:
        Async SQLAlchemy engine with initialized schema

    Cleanup:
        Disposes engine after test
    """
    # Create sync engine first to create tables
    sync_url = f"sqlite:///{temp_db_path}"
    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    # Create async engine for tests
    async_url = f"sqlite+aiosqlite:///{temp_db_path}"
    engine = create_async_engine(async_url, echo=False)

    # Enable foreign key constraints for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for direct SQL operations.

    Args:
        db_engine: Async SQLAlchemy engine

    Yields:
        AsyncSession for database operations

    Cleanup:
        Closes session and rolls back any uncommitted changes
    """
    async_session = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def data_layer(
    temp_db_path: Path,
) -> AsyncGenerator[SQLiteSQLAlchemyDataLayer, None]:
    """Create SQLiteSQLAlchemyDataLayer instance.

    Args:
        temp_db_path: Path to temporary database file

    Returns:
        Fully initialized data layer instance

    Cleanup:
        Closes connections after test
    """
    # Create sync engine first to create tables
    sync_url = f"sqlite:///{temp_db_path}"
    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    # Create data layer with async URL
    async_url = f"sqlite+aiosqlite:///{temp_db_path}"
    layer = SQLiteSQLAlchemyDataLayer(
        conninfo=async_url, storage_provider=None, show_logger=False
    )

    # Enable foreign key constraints for SQLite
    @event.listens_for(layer.engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield layer

    # Cleanup
    await layer.engine.dispose()


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample user data dictionary.

    Returns:
        Dict with id, identifier, metadata, createdAt
    """
    return {
        "id": str(uuid.uuid4()),
        "identifier": "test@example.com",
        "metadata": {"role": "user", "preferences": {"theme": "dark"}},
        "createdAt": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_thread_data() -> dict[str, Any]:
    """Sample thread data with tags.

    Returns:
        Dict with all thread fields including tags list
    """
    return {
        "id": str(uuid.uuid4()),
        "name": "Test Thread",
        "userId": str(uuid.uuid4()),
        "userIdentifier": "test@example.com",
        "tags": ["important", "bug", "feature-request"],
        "metadata": {"priority": "high", "assignee": "john"},
        "createdAt": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_step_data(sample_thread_data: dict[str, Any]) -> dict[str, Any]:
    """Sample step data with tags, metadata, and generation.

    Args:
        sample_thread_data: Thread data for threadId

    Returns:
        Dict with all step fields
    """
    return {
        "id": str(uuid.uuid4()),
        "name": "Test Step",
        "type": "tool",
        "threadId": sample_thread_data["id"],
        "parentId": None,
        "streaming": False,
        "waitForAnswer": False,
        "isError": False,
        "tags": ["api-call", "external"],
        "metadata": {"duration": 1.5, "retries": 2},
        "generation": {"model": "gpt-4", "tokens": 150, "temperature": 0.7},
        "input": "Test input",
        "output": "Test output",
        "createdAt": "2024-01-01T00:00:00Z",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-01T00:00:01Z",
        "showInput": "true",
        "language": "python",
        "indent": 0,
    }


@pytest.fixture
def sample_element_data(sample_thread_data: dict[str, Any]) -> dict[str, Any]:
    """Sample element data with props.

    Args:
        sample_thread_data: Thread data for threadId

    Returns:
        Dict with all element fields
    """
    return {
        "id": str(uuid.uuid4()),
        "threadId": sample_thread_data["id"],
        "type": "image",
        "url": "https://example.com/image.png",
        "name": "Test Image",
        "display": "inline",
        "props": {"width": 800, "height": 600, "format": "png"},
        "forId": str(uuid.uuid4()),
    }


@pytest.fixture
def sample_feedback_data(
    sample_thread_data: dict[str, Any], sample_step_data: dict[str, Any]
) -> dict[str, Any]:
    """Sample feedback data.

    Args:
        sample_thread_data: Thread data for threadId
        sample_step_data: Step data for forId

    Returns:
        Dict with feedback fields
    """
    return {
        "id": str(uuid.uuid4()),
        "forId": sample_step_data["id"],
        "threadId": sample_thread_data["id"],
        "value": 1,
        "comment": "Great response!",
    }


@pytest_asyncio.fixture
async def create_user(
    data_layer: SQLiteSQLAlchemyDataLayer,
) -> AsyncGenerator[Callable, None]:
    """Factory fixture to create users.

    Args:
        data_layer: Data layer instance

    Returns:
        Async function that creates users

    Usage:
        user = await create_user(identifier="test@example.com", metadata={})
    """
    created_users: list[str] = []

    async def _create_user(
        identifier: str | None = None, metadata: dict | None = None
    ) -> dict[str, Any]:
        from chainlit.user import User

        if identifier is None:
            identifier = f"test-{uuid.uuid4()}@example.com"
        if metadata is None:
            metadata = {}

        user = User(identifier=identifier, metadata=metadata)
        persisted_user = await data_layer.create_user(user)
        if persisted_user:
            created_users.append(persisted_user.id)
            return {
                "id": persisted_user.id,
                "identifier": persisted_user.identifier,
                "metadata": persisted_user.metadata,
                "createdAt": persisted_user.createdAt,
            }
        return {}

    yield _create_user

    # Cleanup is handled by database teardown


@pytest_asyncio.fixture
async def create_thread(
    data_layer: SQLiteSQLAlchemyDataLayer,
) -> AsyncGenerator[Callable, None]:
    """Factory fixture to create threads.

    Args:
        data_layer: Data layer instance

    Returns:
        Async function that creates threads

    Usage:
        thread_id = await create_thread(name="Test", tags=["tag1"])
    """
    created_threads: list[str] = []

    async def _create_thread(
        thread_id: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        if thread_id is None:
            thread_id = str(uuid.uuid4())
        if name is None:
            name = f"Test Thread {thread_id[:8]}"

        await data_layer.update_thread(
            thread_id=thread_id,
            name=name,
            user_id=user_id,
            tags=tags,
            metadata=metadata,
        )
        created_threads.append(thread_id)
        return thread_id

    yield _create_thread

    # Cleanup is handled by database teardown


@pytest_asyncio.fixture
async def raw_db_query(db_session: AsyncSession) -> Callable:
    """Execute raw SQL queries for verification.

    Args:
        db_session: Database session

    Returns:
        Async function to execute raw SQL

    Usage:
        result = await raw_db_query('SELECT * FROM users WHERE id = :id', {"id": "123"})
    """

    async def _execute_query(query: str, params: dict | None = None) -> Any:
        if params is None:
            params = {}
        result = await db_session.execute(text(query), params)
        # For SELECT queries
        try:
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
        except Exception:
            # For INSERT/UPDATE/DELETE queries
            await db_session.commit()
            return cast(CursorResult[Any], result).rowcount

    return _execute_query
