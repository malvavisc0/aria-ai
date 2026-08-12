"""Database operations for planner persistence."""

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.engine import CursorResult

from aria.tools.database import get_tools_database

from .models import PlanModel, PlanStepModel


class PlannerDatabase:
    """Database manager for planner persistence."""

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
        self._tools_db.create_tables()  # ensures planner tables exist
        self._initialized = True
        logger.info("PlannerDatabase initialized")

    def get_session(self):
        return self._tools_db.get_session()

    def save_plan(
        self,
        plan_id: str,
        agent_id: str,
        task: str,
        steps: list[dict],
        created_at: str,
    ) -> None:
        """Save a new plan with its steps."""
        with self.get_session() as session:
            # Create plan
            plan = PlanModel(
                id=plan_id,
                agent_id=agent_id,
                task=task,
                created_at=datetime.fromisoformat(created_at),
                updated_at=datetime.now(UTC),
                is_active=True,
            )
            session.add(plan)

            # Create steps
            for idx, step_data in enumerate(steps):
                step = PlanStepModel(
                    plan_id=plan_id,
                    step_id=step_data["id"],
                    step_number=idx,
                    description=step_data["description"],
                    status=step_data.get("status", "pending"),
                    result=step_data.get("result"),
                    created_at=datetime.fromisoformat(step_data["created_at"]),
                    updated_at=datetime.fromisoformat(step_data["updated_at"]),
                )
                session.add(step)

            session.commit()
            logger.debug(f"Saved plan {plan_id} with {len(steps)} steps")

    def load_plan(self, plan_id: str) -> dict | None:
        """Load a plan by its ID."""
        with self.get_session() as session:
            stmt = select(PlanModel).where(
                PlanModel.id == plan_id,
                PlanModel.is_active.is_(True),
            )
            plan_model = session.execute(stmt).scalar_one_or_none()

            if not plan_model:
                return None

            steps = []
            for step in plan_model.steps:
                steps.append(
                    {
                        "id": step.step_id,
                        "description": step.description,
                        "status": step.status,
                        "result": step.result,
                        "created_at": step.created_at.isoformat(),
                        "updated_at": step.updated_at.isoformat(),
                    }
                )

            return {
                "plan_id": plan_model.id,
                "agent_id": plan_model.agent_id,
                "task": plan_model.task,
                "created_at": plan_model.created_at.isoformat(),
                "updated_at": plan_model.updated_at.isoformat(),
                "is_active": plan_model.is_active,
                "steps": steps,
            }

    def update_step(
        self,
        plan_id: str,
        step_id: str,
        status: str | None = None,
        result: str | None = None,
        description: str | None = None,
    ) -> bool:
        """Update a step in a plan."""
        with self.get_session() as session:
            stmt = select(PlanStepModel).where(
                PlanStepModel.plan_id == plan_id,
                PlanStepModel.step_id == step_id,
            )
            step_model = session.execute(stmt).scalar_one_or_none()

            if not step_model:
                return False

            if status is not None:
                step_model.status = status
            if result is not None:
                step_model.result = result
            if description is not None:
                step_model.description = description
            step_model.updated_at = datetime.now(UTC)

            # Update plan timestamp
            plan_stmt = select(PlanModel).where(PlanModel.id == plan_id)
            plan_model = session.execute(plan_stmt).scalar_one()
            plan_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Updated step {step_id} in plan {plan_id}")
            return True

    def add_step(
        self,
        plan_id: str,
        step_id: str,
        description: str,
        after_step_id: str | None,
    ) -> dict | None:
        """Add a step to a plan."""
        with self.get_session() as session:
            # Get plan and steps
            stmt = select(PlanModel).where(PlanModel.id == plan_id)
            plan_model = session.execute(stmt).scalar_one_or_none()

            if not plan_model:
                return None

            # Convert steps to list to avoid iterator exhaustion
            steps_list = list(plan_model.steps)

            # Determine step number
            if after_step_id is None:
                # Add at end
                max_step_num = max((s.step_number for s in steps_list), default=-1)
                step_number = max_step_num + 1
            else:
                # Find after_step_id position and shift subsequent steps
                step_number = None
                for step in steps_list:
                    if step.step_id == after_step_id:
                        step_number = step.step_number + 1
                        break
                else:
                    return None

                # Shift steps that come after (within the same session)
                for step in steps_list:
                    if step.step_number >= step_number:
                        step.step_number += 1

            now = datetime.now(UTC)
            new_step = PlanStepModel(
                plan_id=plan_id,
                step_id=step_id,
                step_number=step_number,
                description=description,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            session.add(new_step)

            # Update plan timestamp
            plan_model.updated_at = datetime.now(UTC)

            session.commit()

            return {
                "id": new_step.step_id,
                "description": new_step.description,
                "status": new_step.status,
                "result": new_step.result,
                "created_at": new_step.created_at.isoformat(),
                "updated_at": new_step.updated_at.isoformat(),
            }

    def remove_step(self, plan_id: str, step_id: str) -> dict | None:
        """Remove a step from a plan."""
        with self.get_session() as session:
            stmt = select(PlanStepModel).where(
                PlanStepModel.plan_id == plan_id,
                PlanStepModel.step_id == step_id,
            )
            step_model = session.execute(stmt).scalar_one_or_none()

            if not step_model:
                return None

            removed_number = step_model.step_number
            removed_data = {
                "id": step_model.step_id,
                "description": step_model.description,
            }

            session.delete(step_model)

            # Renumber subsequent steps
            remaining_stmt = (
                select(PlanStepModel)
                .where(
                    PlanStepModel.plan_id == plan_id,
                    PlanStepModel.step_number > removed_number,
                )
                .order_by(PlanStepModel.step_number)
            )
            remaining_steps = session.execute(remaining_stmt).scalars().all()

            for step in remaining_steps:
                step.step_number -= 1

            # Update plan timestamp
            plan_stmt = select(PlanModel).where(PlanModel.id == plan_id)
            plan_model = session.execute(plan_stmt).scalar_one()
            plan_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Removed step {step_id} from plan {plan_id}")
            return removed_data

    def reorder_steps(self, plan_id: str, step_ids: list[str]) -> list[dict] | None:
        """Reorder steps in a plan."""
        with self.get_session() as session:
            # Get plan
            stmt = select(PlanModel).where(PlanModel.id == plan_id)
            plan_model = session.execute(stmt).scalar_one_or_none()

            if not plan_model:
                return None

            # Build lookup
            step_lookup = {s.step_id: s for s in plan_model.steps}

            # Validate all step_ids exist
            if set(step_ids) != set(step_lookup.keys()):
                return None

            # Reorder
            reordered = []
            for idx, sid in enumerate(step_ids):
                step = step_lookup[sid]
                step.step_number = idx
                step.updated_at = datetime.now(UTC)
                reordered.append(
                    {
                        "position": idx + 1,
                        "id": step.step_id,
                        "description": step.description,
                        "status": step.status,
                        "result": step.result,
                        "created_at": step.created_at.isoformat(),
                        "updated_at": step.updated_at.isoformat(),
                    }
                )

            # Update plan timestamp
            plan_model.updated_at = datetime.now(UTC)

            session.commit()
            logger.debug(f"Reordered steps for plan {plan_id}")
            return reordered

    def delete_plan(self, plan_id: str) -> bool:
        """Soft-delete a plan."""
        with self.get_session() as session:
            stmt = select(PlanModel).where(PlanModel.id == plan_id)
            plan_model = session.execute(stmt).scalar_one_or_none()

            if not plan_model:
                return False

            plan_model.is_active = False
            plan_model.updated_at = datetime.now(UTC)
            session.commit()
            logger.debug(f"Deleted plan {plan_id}")
            return True

    def list_plans(self, agent_id: str | None = None) -> list[dict]:
        """List all active plans."""
        with self.get_session() as session:
            stmt = (
                select(PlanModel)
                .where(PlanModel.is_active.is_(True))
                .order_by(PlanModel.updated_at.desc())
            )

            if agent_id:
                stmt = stmt.where(PlanModel.agent_id == agent_id)

            plans = session.execute(stmt).scalars().all()

            return [
                {
                    "plan_id": p.id,
                    "agent_id": p.agent_id,
                    "task": p.task,
                    "created_at": p.created_at.isoformat(),
                    "updated_at": p.updated_at.isoformat(),
                }
                for p in plans
            ]

    def cleanup_old_plans(self, days: int = 30, agent_id: str | None = None) -> int:
        """Permanently delete inactive plans older than specified days."""
        with self.get_session() as session:
            cutoff_date = datetime.now(UTC) - timedelta(days=days)

            from sqlalchemy import delete as sa_delete

            stmt = sa_delete(PlanModel).where(
                PlanModel.is_active.is_(False),
                PlanModel.updated_at < cutoff_date,
            )

            if agent_id:
                stmt = stmt.where(PlanModel.agent_id == agent_id)

            result: CursorResult = session.execute(stmt)  # type: ignore[assignment]
            count = result.rowcount

            session.commit()
            logger.info(f"Cleaned up {count} old plans")
            return count

    def close(self) -> None:
        """Close is handled by the shared ToolsDatabase."""
        pass
