"""Application state management for the Aria web UI.

This module provides the global application state that is initialized
at startup and used throughout the application. It includes:
- AppState: Pydantic model holding all application-wide state
- AppStateNotInitializedError: Exception raised when state accessed before init

The state is managed as a singleton instance (`_state`) that is populated
by the lifecycle handlers in `lifecycle.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from chromadb.api import ClientAPI
from llama_index.core.agent.workflow import AgentWorkflow
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.llms.openai_like import OpenAILike
from pydantic import BaseModel
from sqlalchemy import Engine

from aria.agents.prompt_enhancer import PromptEnhancerAgent
from aria.server.vllm import VllmServerManager

ROOT_MESSAGE_TYPES = ["user_message", "assistant_message"]


class AppStateNotInitializedError(RuntimeError):
    """Raised when AppState attributes are accessed before initialization.

    This exception is raised when code attempts to use application state
    before the startup handler has completed initialization.
    """

    def __init__(self, message: str = "AppState is not fully initialized") -> None:
        super().__init__(message)


_REQUIRED_FIELDS = (
    "llm",
    "embeddings",
    "vector_db",
    "agents_workflow",
    "db_engine",
)


class AppState(BaseModel):
    """Application state initialized at startup.

    This Pydantic model holds all application-wide state including:
    - LLM and embeddings clients
    - Vector database connection
    - Agent workflow
    - vLLM server manager
    - Browser manager
    - Database engine

    The state is populated by on_app_startup_handler() in lifecycle.py
    and cleaned up by on_app_shutdown_handler().
    """

    model_config = {"arbitrary_types_allowed": True}

    llm: OpenAILike | None = None
    embeddings: BaseEmbedding | None = None
    vector_db: ClientAPI | None = None
    agents_workflow: AgentWorkflow | None = None
    prompt_enhancer: PromptEnhancerAgent | None = None
    vllm_manager: VllmServerManager | None = None
    browser_manager: Any = None
    voice_manager: Any = None
    db_engine: Engine | None = None
    startup_complete: bool = False
    startup_event: asyncio.Event = asyncio.Event()

    def is_initialized(self) -> bool:
        """Check if the application state is fully initialized.

        Returns:
            bool: True if all required components are initialized.
        """
        return (
            all(getattr(self, field) is not None for field in _REQUIRED_FIELDS)
            and self.startup_complete
        )

    def validate_initialized(self) -> None:
        """Validate that the application state is fully initialized."""
        if not self.is_initialized():
            missing = [f for f in _REQUIRED_FIELDS if getattr(self, f) is None]
            if not self.startup_complete:
                missing.append("startup_complete")
            raise AppStateNotInitializedError(f"Not initialized: {', '.join(missing)}")


# NOTE: _state is a mutable singleton accessed from multiple async coroutines.
# This is safe under CPython's GIL given the startup-once pattern, but should
# be revisited if true parallelism is introduced. Consider adding an
# asyncio.Lock if concurrent writes become necessary.
_state = AppState()
