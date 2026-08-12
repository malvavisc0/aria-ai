"""Database operations for memory store persistence."""

import json
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select

from aria.tools.database import get_tools_database

from .models import MemoryEntryModel


class MemoryDatabase:
    """Database manager for memory store persistence."""

    _initialized: bool
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        self._initialized = getattr(self, "_initialized", False)
        if self._initialized:
            return

        self._tools_db = get_tools_database()
        self._tools_db.create_tables()
        self._initialized = True
        logger.info("MemoryDatabase initialized")

    def get_session(self):
        return self._tools_db.get_session()

    def store(
        self,
        entry_id: str,
        agent_id: str,
        key: str,
        value: str,
        tags: list[str] | None = None,
    ) -> None:
        """Store a new memory entry."""
        with self.get_session() as session:
            entry = MemoryEntryModel(
                id=entry_id,
                agent_id=agent_id,
                key=key,
                value=value,
                tags=json.dumps(tags) if tags else None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                is_active=True,
            )
            session.add(entry)
            session.commit()
            logger.debug(f"Stored memory entry {entry_id} with key '{key}'")

    def recall(self, agent_id: str, key: str) -> dict | None:
        """Recall a memory entry by key."""
        with self.get_session() as session:
            stmt = (
                select(MemoryEntryModel)
                .where(
                    MemoryEntryModel.agent_id == agent_id,
                    MemoryEntryModel.key == key,
                    MemoryEntryModel.is_active.is_(True),
                )
                .order_by(MemoryEntryModel.updated_at.desc())
            )
            entry = session.execute(stmt).scalar_one_or_none()

            if entry is None:
                return None

            return {
                "id": entry.id,
                "key": entry.key,
                "value": entry.value,
                "tags": json.loads(entry.tags) if entry.tags else [],
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
            }

    def search(
        self,
        agent_id: str,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """Search memory entries by key or value substring."""
        with self.get_session() as session:
            pattern = f"%{query}%"
            stmt = (
                select(MemoryEntryModel)
                .where(
                    MemoryEntryModel.agent_id == agent_id,
                    MemoryEntryModel.is_active.is_(True),
                )
                .where(
                    MemoryEntryModel.key.ilike(pattern)
                    | MemoryEntryModel.value.ilike(pattern)
                )
                .order_by(MemoryEntryModel.updated_at.desc())
                .limit(max_results)
            )
            entries = session.execute(stmt).scalars().all()

            return [
                {
                    "id": e.id,
                    "key": e.key,
                    "value": e.value,
                    "tags": json.loads(e.tags) if e.tags else [],
                    "created_at": e.created_at.isoformat(),
                    "updated_at": e.updated_at.isoformat(),
                }
                for e in entries
            ]

    def list_entries(
        self,
        agent_id: str,
        tag: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        """List all memory entries for an agent."""
        with self.get_session() as session:
            stmt = select(MemoryEntryModel).where(
                MemoryEntryModel.agent_id == agent_id,
                MemoryEntryModel.is_active.is_(True),
            )

            if tag:
                # Match tag within JSON array string: "tag" with quotes
                # to avoid substring false positives
                stmt = stmt.where(MemoryEntryModel.tags.contains(f'"{tag}"'))

            stmt = stmt.order_by(MemoryEntryModel.updated_at.desc()).limit(max_results)
            entries = session.execute(stmt).scalars().all()

            return [
                {
                    "id": e.id,
                    "key": e.key,
                    "value": e.value,
                    "tags": json.loads(e.tags) if e.tags else [],
                    "created_at": e.created_at.isoformat(),
                    "updated_at": e.updated_at.isoformat(),
                }
                for e in entries
            ]

    def update(self, entry_id: str, agent_id: str, value: str) -> bool:
        """Update a memory entry's value."""
        with self.get_session() as session:
            stmt = select(MemoryEntryModel).where(
                MemoryEntryModel.id == entry_id,
                MemoryEntryModel.agent_id == agent_id,
                MemoryEntryModel.is_active.is_(True),
            )
            entry = session.execute(stmt).scalar_one_or_none()

            if entry is None:
                return False

            entry.value = value
            entry.updated_at = datetime.now(UTC)
            session.commit()
            logger.debug(f"Updated memory entry {entry_id}")
            return True

    def delete(self, entry_id: str, agent_id: str) -> bool:
        """Soft-delete a memory entry."""
        with self.get_session() as session:
            stmt = select(MemoryEntryModel).where(
                MemoryEntryModel.id == entry_id,
                MemoryEntryModel.agent_id == agent_id,
                MemoryEntryModel.is_active.is_(True),
            )
            entry = session.execute(stmt).scalar_one_or_none()

            if entry is None:
                return False

            entry.is_active = False
            entry.updated_at = datetime.now(UTC)
            session.commit()
            logger.debug(f"Deleted memory entry {entry_id}")
            return True


def get_database() -> MemoryDatabase:
    """Get the memory database singleton."""
    return MemoryDatabase()
