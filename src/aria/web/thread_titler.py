"""Generate concise thread titles via a lightweight vLLM call.

Chainlit's default behaviour names a thread after the first user message
verbatim.  This module replaces that with an LLM-generated title after the
first successful turn, falling back silently to the Chainlit default on
any failure.
"""

from __future__ import annotations

from loguru import logger

from aria.llm.utility import utility_completion
from aria.web.hooks import get_data_layer_handler

_TITLE_SYSTEM_PROMPT = (
    "Generate a concise title (max 6 words) for the conversation below. "
    "Return only the title text — no quotes, no trailing punctuation, "
    "no explanation."
)

_MAX_TITLE_CHARS = 80


async def generate_thread_title(
    user_message: str,
    assistant_reply: str,
) -> str | None:
    """Ask the vLLM for a short conversation title.

    Returns the title, or ``None`` on any failure (network error, empty
    response, etc.).  The caller is expected to keep the existing name
    when ``None`` is returned.
    """
    title = await utility_completion(
        messages=[
            {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"User: {user_message}\n\nAssistant: {assistant_reply}",
            },
        ],
        max_tokens=50,
        temperature=0.1,
        timeout=15.0,
    )
    title = title.strip()
    if not title:
        return None
    return title[:_MAX_TITLE_CHARS]


async def maybe_title_thread(
    thread_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Generate a title, persist it, and push the new name to the UI.

    Chainlit's ``init_thread`` does two things: it calls
    ``data_layer.update_thread(name=...)`` to persist, then emits a
    ``first_interaction`` socket event so the frontend updates the
    sidebar live.  We must do the same — persisting alone leaves the
    UI showing the stale first-message name until a page reload.

    Never raises — on any failure the existing (Chainlit-default) name is
    kept.  Intended to be called as a fire-and-forget background task
    after the first successful turn.
    """
    try:
        title = await generate_thread_title(user_message, assistant_reply)
        if not title:
            logger.debug("Thread title generation returned empty; keeping default")
            return
        data_layer = get_data_layer_handler()
        await data_layer.update_thread(thread_id=thread_id, name=title)
        await _emit_thread_name(thread_id, title)
        logger.info(f"Renamed thread {thread_id} → '{title}'")
    except Exception as e:
        logger.warning(f"Thread title generation failed for {thread_id}: {e}")


async def _emit_thread_name(thread_id: str, name: str) -> None:
    """Push the new thread name to the frontend via the socket.

    Re-uses the ``first_interaction`` event that Chainlit's own
    ``init_thread`` emits — the frontend handler sets the thread name
    and refreshes the sidebar list.
    """
    import chainlit as cl

    await cl.context.emitter.emit(
        "first_interaction",
        {"interaction": name, "thread_id": thread_id},
    )
