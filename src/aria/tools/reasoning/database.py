"""Database operations for reasoning persistence using SQLAlchemy."""

import json
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from aria.tools.database import get_tools_database

from .models import (
    ReasoningReflectionModel,
    ReasoningScratchpadModel,
    ReasoningSessionModel,
    ReasoningStepModel,
    ReasoningToolEventModel,
)


class ReasoningDatabase:
    """Database manager for reasoning sessions using SQLAlchemy."""

    # Instance initialization flag (set in __new__/__init__)
    _initialized: bool

    _instance = None

    def __new__(cls):
        """Singleton pattern for database instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize database connection."""
        # Ensure the attribute exists before accessing it (pylint-friendly).
        self._initialized = getattr(self, "_initialized", False)
        if self._initialized:
            return

        self._tools_db = get_tools_database()
        self._tools_db.create_tables()  # ensures reasoning tables exist
        self._initialized = True
        logger.info("ReasoningDatabase initialized")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self._tools_db.get_session()

    def save_session_metadata(
        self,
        internal_id: str,
        session_id: str,
        agent_id: str,
        created_at: str,
    ) -> None:
        """Save or update session metadata."""
        with self.get_session() as session:
            # Check if session exists
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.id == internal_id
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                # Update existing
                existing.updated_at = datetime.now(UTC)
                existing.is_active = True
            else:
                # Create new
                new_session = ReasoningSessionModel(
                    id=internal_id,
                    session_id=session_id,
                    agent_id=agent_id,
                    created_at=datetime.fromisoformat(created_at),
                    updated_at=datetime.now(UTC),
                    is_active=True,
                )
                session.add(new_session)

            session.commit()
            logger.debug(f"Saved session metadata: {session_id} for agent {agent_id}")

    def _step_to_dict(self, step) -> dict:
        return {
            "id": step.step_number,
            "cognitive_mode": step.cognitive_mode,
            "reasoning_type": step.reasoning_type,
            "content": step.content,
            "confidence": step.confidence,
            "reason": getattr(step, "reason", None),
            "evidence": (json.loads(step.evidence) if step.evidence else []),
            "biases_detected": (
                json.loads(step.biases_detected) if step.biases_detected else []
            ),
            "timestamp": step.timestamp.isoformat(),
        }

    def _reflection_to_dict(self, refl) -> dict:
        return {
            "content": refl.content,
            "step_id": refl.step_id,
            "reason": getattr(refl, "reason", None),
            "timestamp": refl.timestamp.isoformat(),
        }

    def _scratchpad_to_dict(self, item) -> tuple[str, dict]:
        return item.key, {
            "value": item.value,
            "updated": item.updated_at.isoformat(),
            "reason": getattr(item, "reason", None),
        }

    def _tool_event_to_dict(self, ev) -> dict:
        return {
            "tool_name": ev.tool_name,
            "reason": ev.reason,
            "payload": (json.loads(ev.payload_json) if ev.payload_json else None),
            "timestamp": ev.timestamp.isoformat(),
        }

    def load_session(self, session_id: str, agent_id: str) -> dict | None:
        """Load complete session data from database."""
        with self.get_session() as session:
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.session_id == session_id,
                ReasoningSessionModel.agent_id == agent_id,
                ReasoningSessionModel.is_active.is_(True),
            )
            session_model = session.execute(stmt).scalar_one_or_none()

            if not session_model:
                return None

            steps = [self._step_to_dict(s) for s in session_model.steps]
            reflections = [
                self._reflection_to_dict(r) for r in session_model.reflections
            ]
            scratchpad = dict(
                self._scratchpad_to_dict(i) for i in session_model.scratchpad_items
            )
            tool_events = [
                self._tool_event_to_dict(e)
                for e in getattr(session_model, "tool_events", []) or []
            ]

            session_data = {
                "id": session_model.id,
                "session_id": session_model.session_id,
                "agent_id": session_model.agent_id,
                "created_at": session_model.created_at.isoformat(),
                "steps": steps,
                "reflections": reflections,
                "scratchpad": scratchpad,
                "tool_events": tool_events,
                "confidence_trajectory": [step["confidence"] for step in steps],
            }

            logger.debug(f"Loaded session {session_id} for agent {agent_id}")
            return session_data

    def save_step(self, session_internal_id: str, step: dict) -> None:
        """Save a reasoning step."""
        with self.get_session() as session:
            step_model = ReasoningStepModel(
                session_id=session_internal_id,
                step_number=step["id"],
                cognitive_mode=step["cognitive_mode"],
                reasoning_type=step["reasoning_type"],
                content=step["content"],
                confidence=step["confidence"],
                reason=step.get("reason"),
                evidence=json.dumps(step["evidence"]),
                biases_detected=json.dumps(step["biases_detected"]),
                timestamp=datetime.fromisoformat(step["timestamp"]),
            )
            session.add(step_model)

            # Update session timestamp
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.id == session_internal_id
            )
            session_model = session.execute(stmt).scalar_one()
            session_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Saved step {step['id']} for session {session_internal_id}")

    def save_reflection(self, session_internal_id: str, reflection: dict) -> None:
        """Save a reflection."""
        with self.get_session() as session:
            refl_model = ReasoningReflectionModel(
                session_id=session_internal_id,
                content=reflection["content"],
                step_id=reflection.get("step_id"),
                reason=reflection.get("reason"),
                timestamp=datetime.fromisoformat(reflection["timestamp"]),
            )
            session.add(refl_model)

            # Update session timestamp
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.id == session_internal_id
            )
            session_model = session.execute(stmt).scalar_one()
            session_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Saved reflection for session {session_internal_id}")

    def save_scratchpad_item(
        self,
        session_internal_id: str,
        key: str,
        value: str,
        updated_at: str,
        reason: str | None = None,
    ) -> None:
        """Save or update a scratchpad item."""
        with self.get_session() as session:
            # Check if item exists
            stmt = select(ReasoningScratchpadModel).where(
                ReasoningScratchpadModel.session_id == session_internal_id,
                ReasoningScratchpadModel.key == key,
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.value = value
                existing.updated_at = datetime.fromisoformat(updated_at)
                if reason is not None:
                    existing.reason = reason
            else:
                item = ReasoningScratchpadModel(
                    session_id=session_internal_id,
                    key=key,
                    value=value,
                    updated_at=datetime.fromisoformat(updated_at),
                    reason=reason,
                )
                session.add(item)

            session.commit()
            logger.debug(
                f"Saved scratchpad item {key} for session {session_internal_id}"
            )

    def save_tool_event(
        self,
        session_internal_id: str,
        tool_name: str,
        reason: str,
        timestamp: str,
        payload: dict | None = None,
    ) -> None:
        """Persist an audit event for a tool call."""
        with self.get_session() as session:
            ev = ReasoningToolEventModel(
                session_id=session_internal_id,
                tool_name=tool_name,
                reason=reason,
                payload_json=(json.dumps(payload) if payload is not None else None),
                timestamp=datetime.fromisoformat(timestamp),
            )
            session.add(ev)

            # Update session timestamp
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.id == session_internal_id
            )
            session_model = session.execute(stmt).scalar_one()
            session_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(
                f"Saved tool event {tool_name} for session {session_internal_id}",
            )

    def delete_scratchpad_item(self, session_internal_id: str, key: str) -> None:
        """Delete a scratchpad item."""
        with self.get_session() as session:
            stmt = select(ReasoningScratchpadModel).where(
                ReasoningScratchpadModel.session_id == session_internal_id,
                ReasoningScratchpadModel.key == key,
            )
            item = session.execute(stmt).scalar_one_or_none()

            if item:
                session.delete(item)
                session.commit()
                logger.debug(
                    f"Deleted scratchpad item {key} for session {session_internal_id}"
                )

    def clear_scratchpad(self, session_internal_id: str) -> None:
        """Clear all scratchpad items for a session."""
        with self.get_session() as session:
            stmt = select(ReasoningScratchpadModel).where(
                ReasoningScratchpadModel.session_id == session_internal_id
            )
            items = session.execute(stmt).scalars().all()

            for item in items:
                session.delete(item)

            session.commit()
            logger.debug(f"Cleared scratchpad for session {session_internal_id}")

    def delete_session(self, session_id: str, agent_id: str) -> bool:
        """Mark session as inactive (soft delete)."""
        with self.get_session() as session:
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.session_id == session_id,
                ReasoningSessionModel.agent_id == agent_id,
            )
            session_model = session.execute(stmt).scalar_one_or_none()

            if session_model:
                session_model.is_active = False
                session.commit()
                logger.debug(f"Deleted session {session_id} for agent {agent_id}")
                return True

            return False

    def reset_session(self, session_internal_id: str) -> None:
        """Clear all steps, reflections, and scratchpad for a session."""
        from sqlalchemy import delete as sa_delete

        with self.get_session() as session:
            # Bulk delete all related data
            session.execute(
                sa_delete(ReasoningStepModel).where(
                    ReasoningStepModel.session_id == session_internal_id
                )
            )
            session.execute(
                sa_delete(ReasoningReflectionModel).where(
                    ReasoningReflectionModel.session_id == session_internal_id
                )
            )
            session.execute(
                sa_delete(ReasoningScratchpadModel).where(
                    ReasoningScratchpadModel.session_id == session_internal_id
                )
            )

            # Update session timestamp
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.id == session_internal_id
            )
            session_model = session.execute(stmt).scalar_one()
            session_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Reset session {session_internal_id}")

    def list_sessions(self, agent_id: str | None = None) -> list[dict]:
        """List all active sessions, optionally filtered by agent."""
        with self.get_session() as session:
            stmt = select(ReasoningSessionModel).where(
                ReasoningSessionModel.is_active.is_(True)
            )

            if agent_id:
                stmt = stmt.where(ReasoningSessionModel.agent_id == agent_id)

            stmt = stmt.order_by(ReasoningSessionModel.updated_at.desc())

            sessions = session.execute(stmt).scalars().all()

            return [
                {
                    "session_id": s.session_id,
                    "agent_id": s.agent_id,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in sessions
            ]

    def cleanup_old_sessions(self, days: int = 30, agent_id: str | None = None) -> int:
        """Permanently delete inactive sessions older than specified days."""
        from sqlalchemy import delete as sa_delete

        with self.get_session() as session:
            cutoff_date = datetime.now(UTC) - timedelta(days=days)

            stmt = sa_delete(ReasoningSessionModel).where(
                ReasoningSessionModel.is_active.is_(False),
                ReasoningSessionModel.updated_at < cutoff_date,
            )

            if agent_id:
                stmt = stmt.where(ReasoningSessionModel.agent_id == agent_id)

            result: CursorResult = session.execute(stmt)  # type: ignore[assignment]
            count = result.rowcount

            session.commit()
            logger.info(f"Cleaned up {count} old sessions")
            return count

    def close(self) -> None:
        """Close is handled by the shared ToolsDatabase."""
        pass


def get_database() -> ReasoningDatabase:
    """Get global database instance (singleton via ReasoningDatabase.__new__)."""
    return ReasoningDatabase()
