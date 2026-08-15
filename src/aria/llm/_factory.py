"""Factory functions for constructing LLM clients, workflows, and memory."""

import httpx
from chromadb.api import ClientAPI as ChromaClientAPI
from llama_index.core.agent.workflow import AgentWorkflow
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.memory import (
    BaseMemoryBlock,
    InsertMethod,
    Memory,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.vector_stores.chroma import ChromaVectorStore

from aria.agents import get_chatter_agent

from ._sanitize import SanitizedOpenAILike
from ._state import StatefulAgentWorkflow
from ._utils import get_instructions_extras
from .memory import IdempotentVectorMemoryBlock


def get_chat_llm(
    api_base: str,
    model: str = "",
    api_key: str = "sk-aria",
    *,
    disable_thinking: bool = False,
) -> OpenAILike:
    """Create the chat LLM client used by the application.

    Uses :class:`SanitizedOpenAILike` to sanitise malformed tool-call
    arguments before they reach the vLLM API, preventing 400 errors
    caused by invalid JSON in ``function.arguments``.

    Args:
        api_base: Base URL for the OpenAI-compatible API.
        model: Model name to send in API requests (e.g. ``"Lucy-128k-gguf"``).
        api_key: API key sent in ``Authorization: Bearer`` header.
            Must match the ``--api-key`` used to start the vLLM server.
        disable_thinking: Send ``chat_template_kwargs.enable_thinking=False``
            so a Qwen3-class reasoning model skips its chain-of-thought block.
            Used by headless workers: their thinking is never shown, and the
            block burns the token budget needed for tool calls and plan steps.

    Returns:
        An :class:`OpenAILike` LLM instance configured to talk to
        ``api_base``.
    """
    from aria.config.api import Vllm as VllmConfig

    max_tokens = None
    if VllmConfig.max_tokens > -1:
        max_tokens = VllmConfig.max_tokens

    extra_body: dict = {
        "top_p": VllmConfig.top_p,
        "top_k": VllmConfig.top_k,
        "min_p": VllmConfig.min_p,
        "presence_penalty": VllmConfig.presence_penalty,
        "repetition_penalty": VllmConfig.repetition_penalty,
        "seed": VllmConfig.seed,
    }
    if disable_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    llm = SanitizedOpenAILike(
        api_base=api_base,
        model=model,
        api_key=api_key,
        is_chat_model=True,
        is_function_calling_model=True,
        max_tokens=max_tokens,
        temperature=VllmConfig.temperature,
        reuse_client=True,
        async_http_client=httpx.AsyncClient(  # type: ignore[call-arg]
            timeout=httpx.Timeout(300.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ),
        additional_kwargs={"extra_body": extra_body},
    )

    return llm


def get_agent_workflow(llm: OpenAILike) -> AgentWorkflow:
    """Build the single-agent workflow used by the UI.

    Returns a :class:`StatefulAgentWorkflow` with the unified Aria agent
    as the sole agent. All tools are loaded from the centralized registry
    inside the agent factory — no specialist agents or handoffs.

    Args:
        llm: LLM instance used by the agent.

    Returns:
        A fully constructed :class:`AgentWorkflow`.
    """

    chatter = get_chatter_agent(
        llm=llm,
        extras=get_instructions_extras(agent_name="aria"),
    )

    workflow = StatefulAgentWorkflow(
        agents=[chatter],
        root_agent=chatter.name,
        # Pass None so setup_agent skips the DEFAULT_STATE_PROMPT injection
        # (the framework coerces None to a falsy {}, which skips the state
        # prompt guard).  reduce_state re-seeds a proper WorkflowState on
        # the first ToolCallResult via its `if not state:` fallback.
        initial_state=None,
    )
    return workflow


def get_default_memory(
    vector_db: ChromaClientAPI,
    embed_model: BaseEmbedding,
    thread_id: str,
    token_limit: int = 32768,
) -> Memory:
    """Create a Memory instance backed by a per-thread ChromaDB vector store.

    Uses a vector-retrieval-only memory block: the live ``Memory`` queue
    keeps the most recent turns as raw text, and older turns are
    flushed to Chroma where they are retrieved by semantic similarity
    when relevant to the current user message.

    The historical ``FactExtractionMemoryBlock`` was removed because
    its ``facts`` field is an in-process pydantic attribute that is
    discarded at shutdown — the 75% of flush time it spent running
    ``llm.achat`` per batch bought nothing that survived the process.
    See ``docs/fix-chat-resume-freeze.md`` (Fix 1c).

    Args:
        vector_db: ChromaDB client for the thread collection.
        embed_model: Embedding model for semantic search.
        thread_id: Thread ID used as ChromaDB collection name and session ID.
        token_limit: Total token budget for history + vector context.
            Default 32768 — leaves room for system prompt and tool schemas.

    Returns:
        A configured :class:`Memory` instance.
    """
    collection = vector_db.get_or_create_collection(thread_id)

    block = IdempotentVectorMemoryBlock(
        name="vector_memory",
        vector_store=ChromaVectorStore(chroma_collection=collection),
        embed_model=embed_model,
        similarity_top_k=3,
        retrieval_context_window=2,
        priority=2,
    )
    memory_blocks: list[BaseMemoryBlock] = [block]

    from aria.config.models import Embeddings as EmbeddingsConfig

    memory = Memory.from_defaults(
        session_id=thread_id,
        insert_method=InsertMethod.USER,
        memory_blocks=memory_blocks,
        token_limit=token_limit,
        chat_history_token_ratio=EmbeddingsConfig.chat_history_token_ratio,
        token_flush_size=EmbeddingsConfig.context_size,
    )

    return memory


def get_embeddings_model(
    model_name: str,
    device: str = "cpu",
) -> HuggingFaceEmbedding:
    """Create the embeddings model used by the application.

    Loads the model in-process via HuggingFace transformers — no separate
    embedding server required.  The native tokenizer handles truncation
    automatically, so long inputs (e.g. tool outputs) never crash the
    embedding call.

    Args:
        model_name: HuggingFace model ID or local path.
        device: Device to run on (``"cpu"`` or ``"cuda"``). Aria's venv ships
            CPU-only torch (pinned via the ``[tool.uv]`` pytorch-cpu index in
            ``pyproject.toml``), so ``"cuda"`` will fail to find CUDA unless the
            venv is re-synced with a CUDA torch backend or embeddings are moved
            to an HTTP endpoint (``llama-index-embeddings-openai-like`` pointed
            at a vLLM ``/v1/embeddings`` server). See ``docs/plan-cpu-torch.md``.

    Returns:
        A :class:`HuggingFaceEmbedding` instance.
    """
    return HuggingFaceEmbedding(
        model_name=model_name,
        device=device,
        trust_remote_code=True,
    )
