"""Database operations for standalone scratchpad persistence."""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.engine import CursorResult

from aria.tools.database import get_tools_database
from aria.tools.models import ScratchpadItemModel


class ScratchpadDatabase:
    """Database manager for standalone scratchpad persistence."""

    _instance = None
    _initialized: bool

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
        logger.info("ScratchpadDatabase initialized")

    def get_session(self):
        return self._tools_db.get_session()

    def set_item(
        self,
        agent_id: str,
        key: str,
        value: str,
        reason: str | None = None,
    ) -> None:
        """Set a scratchpad item (upsert by agent_id + key)."""
        with self.get_session() as session:
            stmt = select(ScratchpadItemModel).where(
                ScratchpadItemModel.agent_id == agent_id,
                ScratchpadItemModel.key == key,
                ScratchpadItemModel.is_active.is_(True),
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.value = value
                existing.reason = reason
                existing.updated_at = datetime.now(UTC)
            else:
                item = ScratchpadItemModel(
                    agent_id=agent_id,
                    key=key,
                    value=value,
                    reason=reason,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    is_active=True,
                )
                session.add(item)

            session.commit()
            logger.debug(f"Scratchpad set: {key} for agent {agent_id}")

    def get_item(self, agent_id: str, key: str) -> dict | None:
        """Get a scratchpad item by key."""
        with self.get_session() as session:
            stmt = select(ScratchpadItemModel).where(
                ScratchpadItemModel.agent_id == agent_id,
                ScratchpadItemModel.key == key,
                ScratchpadItemModel.is_active.is_(True),
            )
            item = session.execute(stmt).scalar_one_or_none()

            if item is None:
                return None

            return {
                "key": item.key,
                "value": item.value,
                "reason": item.reason,
                "updated_at": item.updated_at.isoformat(),
            }

    def delete_item(self, agent_id: str, key: str) -> bool:
        """Soft-delete a scratchpad item."""
        with self.get_session() as session:
            stmt = select(ScratchpadItemModel).where(
                ScratchpadItemModel.agent_id == agent_id,
                ScratchpadItemModel.key == key,
                ScratchpadItemModel.is_active.is_(True),
            )
            item = session.execute(stmt).scalar_one_or_none()

            if item is None:
                return False

            item.is_active = False
            item.updated_at = datetime.now(UTC)
            session.commit()
            logger.debug(f"Scratchpad deleted: {key} for agent {agent_id}")
            return True

    def list_items(self, agent_id: str) -> list[dict]:
        """List all active scratchpad items for an agent."""
        with self.get_session() as session:
            stmt = (
                select(ScratchpadItemModel)
                .where(
                    ScratchpadItemModel.agent_id == agent_id,
                    ScratchpadItemModel.is_active.is_(True),
                )
                .order_by(ScratchpadItemModel.updated_at.desc())
            )
            items = session.execute(stmt).scalars().all()

            return [
                {
                    "key": item.key,
                    "value": item.value,
                    "reason": item.reason,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in items
            ]

    def clear_all(self, agent_id: str) -> int:
        """Soft-delete all scratchpad items for an agent.

        Returns:
            Number of items cleared.
        """
        from sqlalchemy import update as sa_update

        with self.get_session() as session:
            now = datetime.now(UTC)
            stmt = (
                sa_update(ScratchpadItemModel)
                .where(
                    ScratchpadItemModel.agent_id == agent_id,
                    ScratchpadItemModel.is_active.is_(True),
                )
                .values(is_active=False, updated_at=now)
            )
            result: CursorResult = session.execute(stmt)  # type: ignore[assignment]
            count = result.rowcount
            session.commit()
            logger.debug(f"Scratchpad cleared {count} items for agent {agent_id}")
            return count


def get_database() -> ScratchpadDatabase:
    """Get the scratchpad database singleton."""
    return ScratchpadDatabase()
