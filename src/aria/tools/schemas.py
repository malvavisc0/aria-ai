"""Explicit Pydantic schemas for tools that need them.

llama-index's auto-schema generation does NOT extract descriptions from
docstrings.  Every parameter must carry a ``Field(description=...)`` so
the LLM understands what to pass.  This file centralises schemas for
tools whose modules haven't been updated yet.
"""

from pydantic import BaseModel, Field


class PlanSchema(BaseModel):
    """Schema exposed to the LLM for the plan tool."""

    reason: str = Field(
        description="Required. Brief explanation of why you are calling this tool."
    )
    action: str = Field(
        description=(
            "Action: 'create' (new plan), 'add_step', 'update_step', "
            "'execute_step', 'complete_step', 'fail_step', "
            "'skip_step', 'update', 'summary', 'delete', 'list', 'status'."
        )
    )
    task: str | None = Field(
        default=None,
        description="Task description (required for 'create').",
    )
    steps: list[str] | None = Field(
        default=None,
        description="List of step descriptions (optional for 'create').",
    )
    step_id: str | None = Field(
        default=None,
        description="Step ID to target (required for step actions).",
    )
    status: str | None = Field(
        default=None,
        description="Status to set: 'pending', 'in_progress', 'completed', 'failed', 'skipped'.",
    )
    result: str | None = Field(
        default=None,
        description="Result text for a step (used with 'update_step').",
    )
    description: str | None = Field(
        default=None,
        description="Updated description (used with 'update_step').",
    )
    after_step_id: str | None = Field(
        default=None,
        description="Insert a new step after this step ID (for 'add_step').",
    )
    step_ids: list[str] | None = Field(
        default=None,
        description="List of step IDs (used with 'execute_step' for batch).",
    )
    execution_id: str | None = Field(
        default=None,
        description="Execution ID for tracking batch operations.",
    )
    agent_id: str = Field(
        default="default",
        description="Auto-set. Do not provide.",
    )


class ScratchpadSchema(BaseModel):
    """Schema exposed to the LLM for the scratchpad tool."""

    reason: str = Field(
        description="Required. Brief explanation of why you are using the scratchpad."
    )
    key: str = Field(
        description="Unique key to identify this scratchpad entry.",
    )
    value: str | None = Field(
        default=None,
        description="Value to store (required for 'set' and 'append' operations).",
    )
    operation: str = Field(
        default="get",
        description=(
            "Operation: 'get' (read), 'set' (create/update), "
            "'append' (add to existing), 'delete', 'list'."
        ),
    )
    agent_id: str = Field(
        default="aria",
        description="Auto-set. Do not provide.",
    )


class CopyFileSchema(BaseModel):
    """Schema exposed to the LLM for copy_file."""

    reason: str = Field(
        description="Required. Brief explanation of why you are copying this file."
    )
    source: str = Field(
        description="Absolute path to the source file.",
    )
    destination: str = Field(
        description="Absolute path to the destination.",
    )
    overwrite: bool | None = Field(
        default=False,
        description="If true, overwrite existing destination file (default: false).",
    )
