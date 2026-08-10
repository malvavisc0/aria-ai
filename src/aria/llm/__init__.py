"""Aria LLM package — public API re-exports for backward compatibility.

All public names that were previously available as ``from aria.llm import …``
continue to work unchanged. The implementation now lives in private submodules
(``_sanitize``, ``_state``, ``_utils``, ``_factory``).
"""

from ._factory import (
    get_agent_workflow,
    get_chat_llm,
    get_default_memory,
    get_embeddings_model,
)
from ._sanitize import SanitizedOpenAILike
from ._state import (
    StatefulAgentWorkflow,
    WorkflowState,
    initial_workflow_state,
    state_reducer,
)
from ._utils import generate_agent_id, get_instructions_extras
from .memory import BackgroundFlushMemory, IdempotentVectorMemoryBlock, wrap_memory
from .utility import utility_completion

__all__ = [
    # _sanitize
    "SanitizedOpenAILike",
    # memory
    "BackgroundFlushMemory",
    "IdempotentVectorMemoryBlock",
    "wrap_memory",
    # _state
    "StatefulAgentWorkflow",
    "WorkflowState",
    "initial_workflow_state",
    "state_reducer",
    # _utils
    "generate_agent_id",
    "get_instructions_extras",
    # _factory
    "get_agent_workflow",
    "get_chat_llm",
    "get_default_memory",
    "get_embeddings_model",
    # utility
    "utility_completion",
]
