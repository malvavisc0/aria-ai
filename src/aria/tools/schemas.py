"""Explicit Pydantic schemas for tools that need them.

llama-index's auto-schema generation does NOT extract descriptions from
docstrings.  Every parameter must carry a ``Field(description=...)`` so
the LLM understands what to pass.  This file centralises schemas for
tools whose modules haven't been updated yet.
"""

from pydantic import BaseModel, Field


class PlanSchema(BaseModel):
    """Schema exposed to the LLM for the plan tool.

    All parameters are optional in JSON so a single schema can serve every
    action; the descriptions state which action requires each field, and the
    server validates per action at call time.
    """

    reason: str = Field(
        description="Required. Brief explanation of why you are calling this tool."
    )
    action: str = Field(
        description=(
            "Action: 'create', 'get', 'update', 'add', 'remove', 'replace', "
            "'reorder', 'list', 'delete', 'cleanup'."
        )
    )
    task: str | None = Field(
        default=None,
        description="Task description (required for 'create').",
    )
    steps: list[str] | None = Field(
        default=None,
        description="Ordered list of step descriptions (required for 'create').",
    )
    execution_id: str | None = Field(
        default=None,
        description=(
            "Plan ID returned by 'create'. Required for 'get', 'update', 'add', "
            "'remove', 'replace', 'reorder', 'delete'."
        ),
    )
    step_id: str | None = Field(
        default=None,
        description="Step ID to target (required for 'update', 'remove', 'replace').",
    )
    status: str | None = Field(
        default=None,
        description=(
            "Step status for 'update': 'pending', 'in_progress', 'completed', 'failed'."
        ),
    )
    result: str | None = Field(
        default=None,
        description="Optional result text recorded on a step (used with 'update').",
    )
    description: str | None = Field(
        default=None,
        description="Step description (required for 'add' and 'replace').",
    )
    after_step_id: str | None = Field(
        default=None,
        description=(
            "Insert the new step after this step ID (for 'add'). Omit/null to "
            "append at the end."
        ),
    )
    step_ids: list[str] | None = Field(
        default=None,
        description=(
            "Full reordered list of every step ID (required for 'reorder'). Must "
            "contain each current step exactly once."
        ),
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
        description="Value to store (required for 'set').",
    )
    operation: str = Field(
        default="get",
        description="Operation: 'get' (read), 'set' (create/update), 'delete', 'list'.",
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
