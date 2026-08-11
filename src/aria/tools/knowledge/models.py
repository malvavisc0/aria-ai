"""SQLAlchemy model for knowledge hub index state."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from aria.tools.models import Base


class KnowledgeIndexStateModel(Base):
    """Per-file index state for idempotent re-indexing.

    ``state`` is ``"indexed"`` (chunks stored in Chroma) or ``"skipped"``
    (no chunks; ``skip_reason`` explains why). ``_is_cached`` treats
    both as "don't re-process if mtime/size unchanged" so deterministic
    skips (too large, unsupported type) aren't retried every run; use
    ``--force`` to retry. Transient errors (conversion/embedding
    failures) are NOT persisted — they're retried on the next run.
    """

    __tablename__ = "knowledge_index_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    mtime: Mapped[float] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
