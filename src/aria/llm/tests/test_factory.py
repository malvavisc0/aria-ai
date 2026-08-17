"""Tests for get_chat_llm factory extra_body construction."""

from __future__ import annotations

from aria.llm._factory import get_chat_llm


def _extra_body(llm) -> dict:
    return llm.additional_kwargs["extra_body"]


def test_thinking_enabled_by_default():
    llm = get_chat_llm(api_base="http://test:9090/v1", model="m")
    assert "chat_template_kwargs" not in _extra_body(llm)


def test_disable_thinking_adds_chat_template_kwargs():
    llm = get_chat_llm(api_base="http://test:9090/v1", model="m", disable_thinking=True)
    assert _extra_body(llm)["chat_template_kwargs"] == {"enable_thinking": False}


def test_disable_thinking_preserves_sampling_params():
    llm = get_chat_llm(api_base="http://test:9090/v1", model="m", disable_thinking=True)
    body = _extra_body(llm)
    for key in ("top_p", "top_k", "min_p", "presence_penalty", "seed"):
        assert key in body


def test_reasoning_effort_included_from_config(monkeypatch) -> None:
    from aria.config.api import Vllm as VllmConfig

    monkeypatch.setattr(VllmConfig, "reasoning_effort", "low")
    llm = get_chat_llm(api_base="http://test:9090/v1", model="m")
    assert _extra_body(llm)["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_when_blank(monkeypatch) -> None:
    from aria.config.api import Vllm as VllmConfig

    monkeypatch.setattr(VllmConfig, "reasoning_effort", "")
    llm = get_chat_llm(api_base="http://test:9090/v1", model="m")
    assert "reasoning_effort" not in _extra_body(llm)
