"""Shared fixtures for planner tests."""

import pytest

from aria.tools.planner.database import PlannerDatabase


@pytest.fixture(autouse=True)
def test_db(test_tools_db):
    """Create a temporary planner database for testing.

    Depends on the shared ``test_tools_db`` fixture (defined in root
    ``conftest.py``) which handles temp-file creation and singleton
    resets.
    """
    test_planner_db = PlannerDatabase()

    import aria.tools.planner.registry as reg_module

    reg_module._DbHolder.db = test_planner_db

    yield test_planner_db
