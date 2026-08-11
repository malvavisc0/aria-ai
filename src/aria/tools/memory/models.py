"""SQLAlchemy models for memory store persistence."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aria.tools.models import Base


class MemoryEntryModel(Base):
    """Model for memory store entries."""

    __tablename__ = "memory_entries"

    # Primary key - UUID
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Agent identifier for multi-agent isolation
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Content key for recall
    key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # The stored value
    value: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional tags for categorization (JSON array string)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Soft delete
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
