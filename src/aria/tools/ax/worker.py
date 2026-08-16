"""Restricted dispatcher surface for background workers."""

from typing import Any

from pydantic import Field

from aria.tools import tool_response
from aria.tools.ax.dispatcher import AxSchema, ax


class WorkerAxSchema(AxSchema):
    """Dispatcher schema without persistent memory or worker delegation."""

    family: str = Field(
        description=(
            "Tool family. Available: web, knowledge, finance, imdb, http, dev, "
            "processes, documents, check, voice, worker (list/status/logs/"
            "cancel/clean only — no spawn), and mcp."
        )
    )


async def worker_ax(
    reason: str = "",
    family: str = "",
    command: str = "",
    args: dict[str, Any] | None = None,
) -> str:
    """Dispatch a worker-safe ax command."""

    if family == "memory":
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "worker_memory_forbidden",
                    "message": "Worker agents do not have persistent conversation memory.",
                }
            },
        )
    if family == "worker" and command == "spawn":
        return tool_response(
            tool="ax",
            reason=reason,
            data={
                "error": {
                    "code": "nested_worker_forbidden",
                    "message": "Worker agents cannot spawn sub-workers.",
                }
            },
        )
    return await ax(reason=reason, family=family, command=command, args=args)
