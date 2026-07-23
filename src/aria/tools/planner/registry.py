"""Planner registry backed by database."""

from loguru import logger

from .database import PlannerDatabase


class _DbHolder:
    db: PlannerDatabase | None = None

    @staticmethod
    def get():
        if _DbHolder.db is None:
            _DbHolder.db = PlannerDatabase()
        return _DbHolder.db


def _get_db() -> PlannerDatabase:
    return _DbHolder.get()


def get_active_plan_id(agent_id: str) -> str | None:
    """Get the most recent active plan ID for an agent."""
    db = _get_db()
    plan_data = db.get_active_plan(agent_id)
    if not plan_data:
        return None
    logger.debug(
        "Resolved active plan '{}' for agent '{}'",
        plan_data["plan_id"],
        agent_id,
    )
    return plan_data["plan_id"]


def plan_exists(plan_id: str) -> bool:
    """Check if a plan exists and is active."""
    db = _get_db()
    return db.load_plan(plan_id) is not None


def get_db() -> PlannerDatabase:
    """Get the database instance."""
    return _get_db()
