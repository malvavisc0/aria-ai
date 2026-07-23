"""Tests for planner functions with database persistence."""

import json


def test_create_plan(test_db):
    """Test creating a plan and verifying it persists."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="create",
        task="Build a web scraper",
        steps=[
            "Install dependencies",
            "Write scraper code",
            "Test the scraper",
        ],
    )

    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["task"] == "Build a web scraper"
    assert data["data"]["result"]["total_steps"] == 3
    assert len(data["data"]["result"]["steps"]) == 3

    # Verify plan is in database
    plan_id = data["data"]["result"]["plan_id"]
    assert test_db.load_plan(plan_id) is not None


def test_get_plan(test_db):
    """Test retrieving a plan by execution_id."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1", "Step 2"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]

    get_result = plan(reason="Testing", action="get", execution_id=plan_id)
    data = json.loads(get_result)

    assert data["data"]["result"]["plan_id"] == plan_id
    assert data["data"]["result"]["task"] == "Test task"


def test_update_step_status(test_db):
    """Test updating step status and verifying in DB."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1", "Step 2"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step_id = json.loads(create_result)["data"]["result"]["steps"][0]["id"]

    # Update step status
    update_result = plan(
        reason="Testing",
        action="update",
        execution_id=plan_id,
        step_id=step_id,
        status="completed",
        result="Worked!",
    )
    data = json.loads(update_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["status"] == "completed"
    assert data["data"]["result"]["result"] == "Worked!"

    # Verify in DB
    get_result = plan(reason="Testing", action="get", execution_id=plan_id)
    plan_data = json.loads(get_result)["data"]["result"]
    updated_step = next(s for s in plan_data["steps"] if s["id"] == step_id)
    assert updated_step["status"] == "completed"
    assert updated_step["result"] == "Worked!"


def test_add_step(test_db):
    """Test adding a step and verifying ordering."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1", "Step 3"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step1_id = json.loads(create_result)["data"]["result"]["steps"][0]["id"]

    # Add step after step 1
    add_result = plan(
        reason="Testing",
        action="add",
        execution_id=plan_id,
        after_step_id=step1_id,
        description="Step 2",
    )
    data = json.loads(add_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["inserted_after"] == step1_id
    assert data["data"]["result"]["total_steps"] == 3


def test_remove_step(test_db):
    """Test removing a step and verifying re-numbering."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1", "Step 2", "Step 3"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step2_id = json.loads(create_result)["data"]["result"]["steps"][1]["id"]

    remove_result = plan(
        reason="Testing",
        action="remove",
        execution_id=plan_id,
        step_id=step2_id,
    )
    data = json.loads(remove_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["remaining_steps"] == 2


def test_replace_step(test_db):
    """Test replacing step description."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Old description"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step_id = json.loads(create_result)["data"]["result"]["steps"][0]["id"]

    replace_result = plan(
        reason="Testing",
        action="replace",
        execution_id=plan_id,
        step_id=step_id,
        description="New description",
    )
    data = json.loads(replace_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["old_description"] == "Old description"
    assert data["data"]["result"]["new_description"] == "New description"


def test_reorder_steps(test_db):
    """Test reordering and verifying new positions."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step A", "Step B", "Step C"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step_ids = [s["id"] for s in json.loads(create_result)["data"]["result"]["steps"]]

    # Reverse the order
    reorder_result = plan(
        reason="Testing",
        action="reorder",
        execution_id=plan_id,
        step_ids=list(reversed(step_ids)),
    )
    data = json.loads(reorder_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["reordered_steps"][0]["description"] == "Step C"
    assert data["data"]["result"]["reordered_steps"][2]["description"] == "Step A"


def test_plan_survives_reload(test_db):
    """Test that plan persists and can be reloaded from DB."""
    from aria.tools.planner import plan

    # Create plan
    create_result = plan(
        reason="Testing",
        action="create",
        task="Persistent task",
        steps=["Step 1", "Step 2"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]

    # Clear registry state (simulate restart)
    import aria.tools.planner.registry as reg_module

    reg_module._DbHolder.db = None

    # Reload plan from DB
    from aria.tools.planner.database import PlannerDatabase

    PlannerDatabase._instance = None
    reg_module._DbHolder.db = PlannerDatabase()

    get_result = plan(reason="Testing", action="get", execution_id=plan_id)
    data = json.loads(get_result)
    assert data["data"]["result"]["task"] == "Persistent task"


def test_invalid_execution_id(test_db):
    """Test error for non-existent plan."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="get",
        execution_id="nonexistent-id",
    )
    data = json.loads(result)
    # Error returns data with an "error" key
    assert "error" in data["data"]


def test_multi_agent_isolation(test_db):
    """Test that two agents have isolated plans."""
    from aria.tools.planner import plan

    # Create plans for two agents
    result1 = plan(
        reason="Testing",
        action="create",
        task="Agent 1 task",
        steps=["Agent 1 Step"],
        agent_id="agent_1",
    )
    result2 = plan(
        reason="Testing",
        action="create",
        task="Agent 2 task",
        steps=["Agent 2 Step"],
        agent_id="agent_2",
    )

    plan1_id = json.loads(result1)["data"]["result"]["plan_id"]
    plan2_id = json.loads(result2)["data"]["result"]["plan_id"]

    # Each agent sees only their plan
    get1 = plan(reason="Test", action="get", execution_id=plan1_id)
    get2 = plan(reason="Test", action="get", execution_id=plan2_id)

    assert json.loads(get1)["data"]["result"]["task"] == "Agent 1 task"
    assert json.loads(get2)["data"]["result"]["task"] == "Agent 2 task"


def test_invalid_step_id(test_db):
    """Test error when updating non-existent step."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]

    result = plan(
        reason="Testing",
        action="update",
        execution_id=plan_id,
        step_id="nonexistent-step",
        status="completed",
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False


def test_invalid_status(test_db):
    """Test error when using invalid status."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]
    step_id = json.loads(create_result)["data"]["result"]["steps"][0]["id"]

    result = plan(
        reason="Testing",
        action="update",
        execution_id=plan_id,
        step_id=step_id,
        status="invalid_status",
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False
    assert "Invalid status" in data["data"]["error"]


def test_invalid_action(test_db):
    """Test error when using invalid action."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="invalid_action",
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False
    assert "Unknown action" in data["data"]["error"]


def test_create_missing_task(test_db):
    """Test error when task is missing for create."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="create",
        steps=["Step 1"],
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False
    assert "task is required" in data["data"]["error"]


def test_create_missing_steps(test_db):
    """Test error when steps is missing for create."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="create",
        task="Test task",
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False
    assert "steps is required" in data["data"]["error"]


def test_update_missing_execution_id(test_db):
    """Test error when execution_id is missing for update."""
    from aria.tools.planner import plan

    result = plan(
        reason="Testing",
        action="update",
        step_id="some-step",
        status="completed",
    )
    data = json.loads(result)
    assert data["data"]["metadata"]["success"] is False
    assert "execution_id is required" in data["data"]["error"]


def test_add_at_end(test_db):
    """Test adding a step at the end (after_step_id=None)."""
    from aria.tools.planner import plan

    create_result = plan(
        reason="Testing",
        action="create",
        task="Test task",
        steps=["Step 1"],
    )
    plan_id = json.loads(create_result)["data"]["result"]["plan_id"]

    # Add step at end
    add_result = plan(
        reason="Testing",
        action="add",
        execution_id=plan_id,
        after_step_id=None,
        description="Step 2",
    )
    data = json.loads(add_result)
    assert data["data"]["metadata"]["success"] is True
    assert data["data"]["result"]["total_steps"] == 2
