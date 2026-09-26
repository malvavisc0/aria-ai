"""OpenInference / Langfuse tracing setup for the web server.

Owns instrumentation bootstrapping and session tagging.  Span payloads
are bounded: without a cap, one workflow run serializes multi-MB state
dumps and embedding vectors into the trace.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger

_LANGFUSE_ENV_KEYS = (
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_BASE_URL",
)

#: Per-attribute cap (chars) applied by the OpenTelemetry SDK at span
#: construction time.
ATTRIBUTE_VALUE_LENGTH_LIMIT = 8192


def init_tracing() -> None:
    """Initialize Langfuse instrumentation if env vars are present."""
    missing = [k for k in _LANGFUSE_ENV_KEYS if not os.getenv(k)]
    if missing:
        logger.warning(
            f"Langfuse instrumentation disabled — "
            f"missing env vars: {', '.join(missing)}"
        )
        return

    from langfuse import get_client
    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation.llama_index import (
        LlamaIndexInstrumentor,
    )

    os.environ.setdefault(
        "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT", str(ATTRIBUTE_VALUE_LENGTH_LIMIT)
    )
    get_client()
    LlamaIndexInstrumentor().instrument(
        config=TraceConfig(hide_embeddings_vectors=True)
    )
    logger.info("Langfuse instrumentation initialized")


@contextmanager
def trace_session(session_id: str, user_id: str = "") -> Iterator[None]:
    """Tag every span created within the block with session/user identity."""
    from openinference.instrumentation import using_attributes

    with using_attributes(session_id=session_id, user_id=user_id):
        yield
