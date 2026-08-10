"""Planner registry backed by database."""

from .database import PlannerDatabase


def _get_db() -> PlannerDatabase:
    return PlannerDatabase()


def get_db() -> PlannerDatabase:
    """Get the database instance."""
    return _get_db()
