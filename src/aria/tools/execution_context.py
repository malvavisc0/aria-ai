"""Execution identity for agent-only tool policy."""

import os
import shlex
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionContext:
    """Identify the agent process invoking a tool."""

    role: str = "aria"
    worker_id: str | None = None


_context: ContextVar[ExecutionContext] = ContextVar(
    "aria_execution_context", default=ExecutionContext()
)


def get_execution_context() -> ExecutionContext:
    """Return the current agent execution identity, including child tools."""

    context = _context.get()
    if context.role == "worker":
        return context

    pid = os.getpid()
    while pid > 1:
        try:
            with open(f"/proc/{pid}/status") as status_file:
                status = status_file.read().splitlines()
            parent = next(line for line in status if line.startswith("PPid:"))
            pid = int(parent.split()[1])
            with open(f"/proc/{pid}/cmdline", "rb") as command_file:
                command = command_file.read().replace(b"\0", b" ")
            argv = shlex.split(command.decode())
        except (FileNotFoundError, StopIteration, ValueError, OSError):
            return context
        if "aria.cli.worker._runner" in argv:
            worker_id = argv[argv.index("--worker-id") + 1]
            return ExecutionContext(role="worker", worker_id=worker_id)
    return context


def set_execution_context(context: ExecutionContext) -> Token[ExecutionContext]:
    """Set the execution identity for the current process context."""

    return _context.set(context)


def reset_execution_context(token: Token[ExecutionContext]) -> None:
    """Restore the execution identity before a temporary override."""

    _context.reset(token)
