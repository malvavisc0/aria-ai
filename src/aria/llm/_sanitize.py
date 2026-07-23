"""Sanitization utilities for malformed tool-call arguments.

vLLM tool-call parsers (e.g. ``qwen3_coder``, ``ministral``) sometimes
produce malformed ``function.arguments`` strings (e.g. two concatenated
JSON objects, trailing garbage, or non-JSON text).  When LlamaIndex
stores these in the chat history and replays them on the next turn,
vLLM's ``_postprocess_messages`` crashes with ``JSONDecodeError: Extra
data``.

This module provides helpers to clean up such arguments and a subclass of
:class:`~llama_index.llms.openai_like.OpenAILike` that applies them
transparently before every API call.
"""

import copy
import json
import re
from typing import Any, Iterable, List, Sequence, cast

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    MessageRole,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
)
from llama_index.llms.openai_like import OpenAILike
from loguru import logger
from openai.types.chat import ChatCompletionMessageParam

_KV_PATTERN = re.compile(
    r'"(\w+)"\s*:\s*' r'("(?:[^"\\]|\\.)*"|[\d.]+|true|false|null)'
)

_JSON_DECODER = json.JSONDecoder()


def _literal_value(raw_v: str) -> Any:
    if raw_v.startswith('"'):
        return json.loads(raw_v)
    if raw_v == "true":
        return True
    if raw_v == "false":
        return False
    if raw_v == "null":
        return None
    try:
        return json.loads(raw_v)
    except (json.JSONDecodeError, ValueError):
        return raw_v


def _regex_recover(arguments: str) -> dict[str, Any] | None:
    matches = _KV_PATTERN.findall(arguments)
    if not matches:
        return None
    recovered = {k: _literal_value(raw_v) for k, raw_v in matches}
    logger.warning("Regex-recovered tool-call arguments: {}", recovered)
    return recovered


def _raw_decode_recover(arguments: str) -> dict[str, Any] | None:
    try:
        obj, _end = _JSON_DECODER.raw_decode(arguments.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict):
        logger.warning(
            "Recovered tool-call arguments from malformed JSON "
            "(truncated at char {}): {}",
            _end,
            arguments[:200],
        )
        return obj
    return {"value": obj}


def _sanitize_tool_call_args(arguments: Any) -> dict[str, Any]:
    """Ensure tool-call arguments are returned as a JSON-safe object.

    The model sometimes emits malformed JSON in ``function.arguments``
    (e.g. two concatenated JSON objects, trailing garbage, or non-JSON
    text).  When this string is forwarded to vLLM's
    ``_postprocess_messages`` it crashes with a 400 Bad Request because
    ``json.loads()`` raises ``JSONDecodeError: Extra data``.

    This helper attempts to recover a valid JSON object from the raw
    string.  If recovery fails, it returns an empty dict ``{}`` so the
    request can at least proceed (the tool will report a missing-argument
    error which is handled gracefully by the agent loop).
    """
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, (list, tuple)):
        return {"value": list(arguments)}
    if arguments is None:
        return {}
    if not isinstance(arguments, str):
        return {"value": arguments}

    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    recovered = _raw_decode_recover(arguments)
    if recovered is not None:
        return recovered

    regex_result = _regex_recover(arguments)
    if regex_result is not None:
        return regex_result

    logger.warning(
        "Could not sanitize tool-call arguments, defaulting to {{}}: {}",
        arguments[:200],
    )
    return {}


def _sanitize_tool_call_arguments_json(arguments: Any) -> str:
    """Return a JSON string safe for OpenAI-compatible `function.arguments`.

    vLLM expects `function.arguments` to remain a JSON string, not a Python
    dict. This helper preserves that wire-format invariant.
    """
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass

    sanitized = _sanitize_tool_call_args(arguments)
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))


def _stringify_block_kwargs(raw: Any) -> str:
    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False)
    if isinstance(raw, str):
        return _sanitize_tool_call_arguments_json(raw)
    return json.dumps(_sanitize_tool_call_args(raw), ensure_ascii=False)


def _sanitize_tool_call_block(
    block: ToolCallBlock,
) -> tuple[ToolCallBlock | None, bool]:
    raw = block.tool_kwargs
    fixed_str = _stringify_block_kwargs(raw)
    if fixed_str == raw:
        return None, False
    logger.debug(
        "Sanitized ToolCallBlock.tool_kwargs: {} → {}",
        repr(raw)[:120],
        repr(fixed_str)[:120],
    )
    return (
        ToolCallBlock(
            tool_name=block.tool_name,
            tool_kwargs=fixed_str,
            tool_call_id=block.tool_call_id,
        ),
        True,
    )


def _ensure_ak_copy(
    ak: dict[str, Any], ak_copy: dict[str, Any] | None
) -> dict[str, Any]:
    if ak_copy is None:
        return copy.deepcopy(ak)
    return ak_copy


def _sanitize_choice_delta_tool_call(
    tc: Any,
    raw_tool_calls: list,
    new_tool_calls: list,
    ak: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None, bool]:
    if not (hasattr(tc, "function") and hasattr(tc.function, "arguments")):
        return tc, None, False
    raw_args = tc.function.arguments
    fixed = _sanitize_tool_call_arguments_json(raw_args)
    if fixed == raw_args:
        return tc, None, False
    logger.debug(
        "Sanitized additional_kwargs tool_call args: {} → {}",
        repr(raw_args)[:120],
        repr(fixed)[:120],
    )
    ak_copy = _ensure_ak_copy(ak, None)
    raw_tool_calls = ak_copy["tool_calls"]
    tc = raw_tool_calls[len(new_tool_calls)]
    tc.function.arguments = fixed
    return tc, ak_copy, True


def _sanitize_dict_tool_call(
    tc: Any,
    raw_tool_calls: list,
    new_tool_calls: list,
    ak: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None, bool]:
    if not isinstance(tc, dict):
        return tc, None, False
    func = tc.get("function", {})
    if "arguments" not in func:
        return tc, None, False
    raw_args = func["arguments"]
    fixed = _sanitize_tool_call_arguments_json(raw_args)
    if fixed == raw_args:
        return tc, None, False
    ak_copy = _ensure_ak_copy(ak, None)
    raw_tool_calls = ak_copy["tool_calls"]
    tc = raw_tool_calls[len(new_tool_calls)]
    func = tc.get("function", {})
    func["arguments"] = fixed
    return tc, ak_copy, True


def _sanitize_additional_kwargs_tool_calls(
    msg: ChatMessage,
) -> tuple[dict[str, Any] | None, bool]:
    ak = msg.additional_kwargs
    if "tool_calls" not in ak:
        return None, False
    raw_tool_calls = ak["tool_calls"]
    new_tool_calls = []
    ak_copy: dict[str, Any] | None = None
    changed = False
    for tc in raw_tool_calls:
        tc, ak_copy, did_change = _sanitize_choice_delta_tool_call(
            tc, raw_tool_calls, new_tool_calls, ak
        )
        if did_change:
            changed = True
        tc, ak_copy_2, did_change = _sanitize_dict_tool_call(
            tc, raw_tool_calls, new_tool_calls, ak
        )
        if did_change:
            changed = True
            ak_copy = ak_copy or ak_copy_2
        new_tool_calls.append(tc)
    return ak_copy if changed else None, changed


def _sanitize_message_blocks(
    msg: ChatMessage,
) -> tuple[list, bool]:
    new_blocks = list(msg.blocks)
    changed = False
    for i, block in enumerate(new_blocks):
        if not isinstance(block, ToolCallBlock):
            continue
        new_block, did_change = _sanitize_tool_call_block(block)
        if did_change and new_block is not None:
            new_blocks[i] = new_block
            changed = True
    return new_blocks, changed


def _build_sanitized_message(
    msg: ChatMessage,
    new_blocks: list,
    ak_copy: dict[str, Any] | None,
) -> ChatMessage:
    return ChatMessage(
        role=msg.role,
        blocks=new_blocks,
        additional_kwargs=ak_copy or msg.additional_kwargs,
        content=msg.content,
    )


def _sanitize_messages(messages: Sequence[ChatMessage]) -> List[ChatMessage]:
    """Return *messages* with tool-call arguments guaranteed to be valid JSON.

    Two code paths carry tool calls inside ``ChatMessage``:

    1. ``ToolCallBlock`` objects in ``message.blocks`` — the modern path.
    2. ``additional_kwargs["tool_calls"]`` — legacy / streaming path
       using ``ChoiceDeltaToolCall`` objects.

    Both are sanitised here so vLLM never sees malformed JSON.
    """
    sanitized: List[ChatMessage] = []
    for msg in messages:
        new_blocks, blocks_changed = _sanitize_message_blocks(msg)
        ak_copy, ak_changed = _sanitize_additional_kwargs_tool_calls(msg)
        if blocks_changed or ak_changed:
            sanitized.append(_build_sanitized_message(msg, new_blocks, ak_copy))
        else:
            sanitized.append(msg)
    return sanitized


def _reorder_system_messages(messages: List[ChatMessage]) -> List[ChatMessage]:
    """Ensure all system messages precede non-system messages.

    The OpenAI-compatible API requires system messages at the beginning
    of the messages array.  Any system messages injected mid-list (e.g. by
    memory blocks or upstream framework changes) are moved to the front.
    """
    system = [m for m in messages if m.role == MessageRole.SYSTEM]
    others = [m for m in messages if m.role != MessageRole.SYSTEM]
    return system + others


class SanitizedOpenAILike(OpenAILike):
    """OpenAILike subclass that sanitizes tool-call arguments before API calls.

    vLLM tool-call parsers (e.g. ``qwen3_coder``, ``ministral``) sometimes
    produce malformed ``function.arguments`` strings (e.g. two concatenated
    JSON objects).  When LlamaIndex stores these in the chat history and
    replays them on the next turn, vLLM's ``_postprocess_messages``
    crashes with ``JSONDecodeError: Extra data``.

    This subclass intercepts ``achat``, ``chat``, and ``astream_chat``
    to clean up any malformed arguments before they reach the API.
    """

    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> "ChatResponse":
        messages = _reorder_system_messages(_sanitize_messages(messages))
        return super().chat(messages, **kwargs)

    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> "ChatResponse":
        messages = _reorder_system_messages(_sanitize_messages(messages))
        return await super().achat(messages, **kwargs)

    async def astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> "ChatResponseAsyncGen":
        messages = _reorder_system_messages(_sanitize_messages(messages))
        return await super().astream_chat(messages, **kwargs)

    async def _astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> "ChatResponseAsyncGen":
        """Override to handle list-typed content deltas.

        Some models (e.g. Claude via OpenRouter, or models with extended
        thinking) return ``delta.content`` as a *list* of content blocks
        instead of a plain string.  The parent implementation crashes with
        ``TypeError: can only concatenate str (not "list") to str`` at
        ``content += content_delta``.

        This override normalises ``delta.content`` so that:
        * Text blocks are extracted and concatenated into a plain string.
        * Thinking blocks are accumulated into ``reasoning_content``.
        """
        # Lazy imports to avoid circular-dependency issues at module
        # load time.
        from llama_index.llms.openai.utils import (
            to_openai_message_dicts,
            update_tool_calls,
        )
        from openai.types.chat.chat_completion_chunk import (
            ChatCompletionChunk,
            ChoiceDelta,
            ChoiceDeltaToolCall,
        )

        aclient = self._get_aclient()
        message_dicts = cast(
            Iterable[ChatCompletionMessageParam],
            to_openai_message_dicts(messages, model=self.model),
        )

        # Extract model/stream explicitly so the type checker can
        # resolve the correct OpenAI SDK overload.
        all_kwargs = self._get_model_kwargs(**kwargs)
        all_kwargs.pop("stream", None)
        _model: str = all_kwargs.pop("model", self.model)

        async def gen() -> "ChatResponseAsyncGen":
            content = ""
            reasoning_content = ""
            tool_calls: List[ChoiceDeltaToolCall] = []
            is_function = False
            first_chat_chunk = True

            async for response in await aclient.chat.completions.create(
                messages=message_dicts,
                model=_model,
                stream=True,
                **all_kwargs,
            ):
                blocks = []
                response = cast(ChatCompletionChunk, response)
                if len(response.choices) > 0:
                    if (
                        first_chat_chunk
                        and response.choices[0].delta.content is None
                        and response.choices[0].delta.tool_calls is None
                        and not getattr(
                            response.choices[0].delta,
                            "reasoning_content",
                            None,
                        )
                    ):
                        first_chat_chunk = False
                        continue
                    delta = response.choices[0].delta
                else:
                    delta = ChoiceDelta()
                first_chat_chunk = False

                if delta is None:
                    continue

                if delta.tool_calls:
                    is_function = True

                role = delta.role or MessageRole.ASSISTANT

                # --- Normalise content delta ---
                raw_content_delta = delta.content
                if isinstance(raw_content_delta, list):
                    text_parts: list[str] = []
                    for block in raw_content_delta:
                        if isinstance(block, dict):
                            btype = block.get("type", "")
                            if btype == "text":
                                text_parts.append(block.get("text", ""))
                            elif btype == "thinking":
                                for tp in block.get("thinking", []):
                                    if (
                                        isinstance(tp, dict)
                                        and tp.get("type") == "text"
                                    ):
                                        reasoning_content += tp.get("text", "")
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content_delta = "".join(text_parts)
                else:
                    content_delta = raw_content_delta or ""
                content += content_delta

                # Extract reasoning_content for chain-of-thought
                # streaming from providers that surface this field.
                # vLLM uses "reasoning" (not "reasoning_content") for
                # its reasoning parser output; some providers (DeepSeek,
                # OpenRouter) use "reasoning_content". Check both.
                raw_reasoning = getattr(delta, "reasoning_content", None)
                if not raw_reasoning:
                    raw_reasoning = getattr(delta, "reasoning", None)
                reasoning_delta = (
                    raw_reasoning if isinstance(raw_reasoning, str) else ""
                )
                reasoning_content += reasoning_delta

                if reasoning_content:
                    blocks.append(ThinkingBlock(content=reasoning_content))
                blocks.append(TextBlock(text=content))

                message_additional_kwargs = {}
                if is_function:
                    tool_calls = update_tool_calls(tool_calls, delta.tool_calls)
                    if tool_calls:
                        message_additional_kwargs["tool_calls"] = tool_calls
                        for tool_call in tool_calls:
                            if tool_call.function:
                                # Keep tool_kwargs as JSON string
                                # (wire format). Fallback to "{}"
                                # not {} (dict) to avoid repr issues.
                                raw_args = tool_call.function.arguments or "{}"
                                blocks.append(
                                    ToolCallBlock(
                                        tool_call_id=tool_call.id,
                                        tool_kwargs=_sanitize_tool_call_arguments_json(
                                            raw_args
                                        ),
                                        tool_name=(tool_call.function.name or ""),
                                    )
                                )

                response_additional_kwargs = self._get_response_token_counts(response)
                if reasoning_delta:
                    response_additional_kwargs["thinking_delta"] = reasoning_delta

                yield ChatResponse(
                    message=ChatMessage(
                        role=role,
                        blocks=blocks,
                        additional_kwargs=message_additional_kwargs,
                    ),
                    delta=content_delta,
                    raw=response,
                    additional_kwargs=response_additional_kwargs,
                )

        return gen()
