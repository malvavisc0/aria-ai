"""Session registry helpers backed by the database."""

from loguru import logger

from .database import ReasoningDatabase, get_database
from .session import ReasoningSession


def _get_db() -> ReasoningDatabase:
    """Get the shared database instance."""
    return get_database()


def get_active_session_id(agent_id: str) -> str | None:
    """Get most-recent active session ID for an agent from the database."""
    sessions = _get_db().list_sessions(agent_id)
    if not sessions:
        return None

    # list_sessions() returns newest-first
    active_session_id = sessions[0]["session_id"]
    logger.debug(
        "Resolved active session '{}' for agent '{}' from database",
        active_session_id,
        agent_id,
    )
    return active_session_id


def get_session(session_id: str, agent_id: str) -> ReasoningSession:
    """Load session from database.

    Args:
        session_id: Session identifier
        agent_id: Agent identifier for multi-agent isolation

    Returns:
        ReasoningSession instance for the given ID

    Raises:
        ValueError: If the session does not exist
    """
    db = _get_db()
    session_data = db.load_session(session_id, agent_id)
    if session_data is None:
        available = [s["session_id"] for s in db.list_sessions(agent_id)]
        logger.error(
            f"Session '{session_id}' for agent '{agent_id}' "
            f"does not exist. Available sessions: {available or ['(none)']}"
        )
        raise ValueError(
            f"Session '{session_id}' for agent '{agent_id}' "
            f"does not exist. Available sessions: {available or ['(none)']}"
        )

    session = ReasoningSession.from_dict(session_data)
    session.set_database(db)
    logger.debug(f"Loaded session {session_id} for agent {agent_id} from database")
    return session


def clear_all() -> None:
    """Reset in-memory state. Kept for test compatibility."""
    # DB-backed registry has no in-memory state to clear.
    return None


def get_db():
    """Get the database instance."""
    return _get_db()
