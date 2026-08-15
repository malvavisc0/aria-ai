"""Tests for the worker-safe ax dispatcher surface (worker_ax)."""

import json

import pytest

from aria.tools.ax.worker import WorkerAxSchema, worker_ax
from aria.tools.registry import CORE, FILES, WORKER_AX, get_tools


def _err(result: str) -> str:
    return json.loads(result)["data"]["error"]["code"]


@pytest.mark.asyncio
async def test_worker_ax_blocks_memory():
    result = await worker_ax(reason="r", family="memory", command="store")
    assert _err(result) == "worker_memory_forbidden"


@pytest.mark.asyncio
async def test_worker_ax_blocks_worker_spawn():
    result = await worker_ax(
        reason="r",
        family="worker",
        command="spawn",
        args={"prompt": "p", "expected": "e", "steps": ["s"]},
    )
    assert _err(result) == "nested_worker_forbidden"


@pytest.mark.asyncio
async def test_worker_ax_allows_web_and_worker_status():
    """Workers keep web access and non-spawn worker commands."""
    result = await worker_ax(reason="r", family="web", command="help")
    assert "error" not in json.loads(result)["data"]
    result = await worker_ax(reason="r", family="worker", command="list")
    assert "error" not in json.loads(result)["data"]


def test_worker_ax_schema_advertises_web_and_worker():
    """Schema description must match the dispatchable surface."""
    desc = WorkerAxSchema.model_json_schema()["properties"]["family"]["description"]
    assert "web" in desc
    assert "worker" in desc
    assert "memory" not in desc


def test_worker_toolset_exposes_single_restricted_ax():
    """The worker agent's ax tool is worker_ax, not the full dispatcher."""
    tools = get_tools([CORE, FILES, WORKER_AX])
    ax_tools = [t for t in tools if t.metadata.name == "ax"]
    assert len(ax_tools) == 1
    assert ax_tools[0].fn is not None
