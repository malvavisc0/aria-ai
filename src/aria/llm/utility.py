"""Utility LLM calls with thinking disabled.

Short, deterministic tasks (image captioning, thread-title generation) must
run with ``enable_thinking=False`` because the chat model is a Qwen3-class
reasoning model — its chain-of-thought block consumes the entire token budget
on these tasks, returning ``content: null`` with ``finish_reason: "length"``.

This module centralises the request shape (URL, auth, model, thinking
override, response parsing) so the ``enable_thinking: False`` override and
the raw-HTTP construction live in exactly one place.
"""

from __future__ import annotations

import httpx

from aria.config.api import Vllm as VllmConfig
from aria.config.models import Chat as ChatConfig


async def utility_completion(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> str:
    """Short LLM call with thinking disabled.

    Args:
        messages: Chat messages (same shape as the OpenAI
            ``/chat/completions`` ``messages`` field).
        max_tokens: Token limit for the response.
        temperature: Sampling temperature. When ``None`` (default) the field
            is omitted from the request body so the vLLM server uses its
            own default. Pass an explicit float to override per-request.
        client: Pre-created ``httpx`` client for connection reuse (e.g.
            when describing multiple images concurrently).  When ``None``
            a short-lived client is created and closed.
        timeout: Request timeout in seconds (used only when *client*
            is ``None``).

    Returns:
        The assistant message content, or an empty string if the model
        returned ``null``.

    Raises:
        httpx.HTTPStatusError: On a non-2xx response from the vLLM server.
    """
    payload: dict = {
        "model": ChatConfig.model,
        "messages": messages,
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    headers = {"Authorization": f"Bearer {VllmConfig.api_key}"}
    url = f"{ChatConfig.api_url}/chat/completions"

    if client is not None:
        response = await client.post(url, headers=headers, json=payload)
    else:
        async with httpx.AsyncClient(timeout=timeout) as c:
            response = await c.post(url, headers=headers, json=payload)

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""
