"""Live integration test for the Lightpanda browser manager.

Starts the real Lightpanda binary, connects via CDP + Playwright,
navigates to a real URL, clicks an element, and exercises concurrent
access to verify the asyncio.Lock serialisation.
"""

import asyncio
import json
from pathlib import Path

import pytest

from aria.tools.browser.manager import LightpandaManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BINARY = Path("data/bin/lightpanda/lightpanda")
PORT = 9334  # Avoid clashing with a running instance on 9222

# Skip the entire module when the Lightpanda binary is not installed
# (e.g. in CI / GitHub Actions).
pytestmark = pytest.mark.skipif(
    not BINARY.exists(),
    reason="Lightpanda binary not installed — skipping live browser tests",
)


@pytest.fixture()
async def manager():
    """Start a fresh Lightpanda instance, yield, then tear down."""
    mgr = LightpandaManager(BINARY, port=PORT)
    started = await mgr.start()
    assert started, "Lightpanda failed to start — is the binary installed?"
    yield mgr
    await mgr.stop()


# ---------------------------------------------------------------------------
# 1. Basic navigate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_returns_content(manager: LightpandaManager):
    """Navigate to a simple page and verify we get structured content."""
    result = await manager.navigate(
        "https://example.com", tool="visit_url", reason="integration test"
    )
    payload = json.loads(result)

    assert payload["status"] == "success"
    assert "example.com" in payload["data"]["url"]
    assert payload["data"]["content_size"] > 0
    assert "Example Domain" in payload["data"]["content_preview"]
    print(
        f"\n✓ navigate: {payload['data']['title']} "
        f"({payload['data']['content_size']} chars)"
    )


# ---------------------------------------------------------------------------
# 2. Sequential navigate (two pages back to back)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_navigations(manager: LightpandaManager):
    """Navigate to two pages sequentially — the second replaces the first."""
    r1 = await manager.navigate(
        "https://example.com", tool="visit_url", reason="page 1"
    )
    p1 = json.loads(r1)
    assert p1["status"] == "success"

    r2 = await manager.navigate(
        "https://httpbin.org/html", tool="visit_url", reason="page 2"
    )
    p2 = json.loads(r2)
    assert p2["status"] == "success"
    assert "httpbin" in p2["data"]["url"]
    print(f"\n✓ sequential: page1={p1['data']['title']}, page2={p2['data']['title']}")


# ---------------------------------------------------------------------------
# 3. Concurrent navigations (the crash scenario)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_navigations_are_serialised(
    manager: LightpandaManager,
):
    """Fire two navigate() calls concurrently.

    Before the fix this would crash with "Execution context was destroyed".
    With the asyncio.Lock they run one after the other and both succeed.
    """
    results = await asyncio.gather(
        manager.navigate(
            "https://example.com", tool="visit_url", reason="concurrent A"
        ),
        manager.navigate(
            "https://httpbin.org/html", tool="visit_url", reason="concurrent B"
        ),
    )
    payloads = [json.loads(r) for r in results]
    statuses = [p["status"] for p in payloads]

    assert all(s == "success" for s in statuses), (
        f"Expected all successes, got: {statuses}"
    )
    print(
        f"\n✓ concurrent: both succeeded — "
        f"{payloads[0]['data']['title']}, {payloads[1]['data']['title']}"
    )


# ---------------------------------------------------------------------------
# 5. Navigate + click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_then_click(manager: LightpandaManager):
    """Navigate to httpbin.org/links/3 and click the first link."""
    r1 = await manager.navigate(
        "https://httpbin.org/links/3", tool="visit_url", reason="before click"
    )
    assert json.loads(r1)["status"] == "success"

    r2 = await manager.click("a", tool="browser_click", reason="clicking first link")
    p2 = json.loads(r2)
    # After clicking, we should have navigated to /links/3/0
    assert p2["status"] == "success"
    assert "httpbin.org" in p2["data"]["url"]
    print(f"\n✓ click: landed on {p2['data']['url']}")


# ---------------------------------------------------------------------------
# 6. Navigate to invalid URL (error handling)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_invalid_url(manager: LightpandaManager):
    """Navigate to a non-existent host — should return a clean error."""
    result = await manager.navigate(
        "https://this-domain-does-not-exist-xyz123.invalid",
        tool="visit_url",
        reason="error test",
    )
    payload = json.loads(result)
    # Should be an error, but the manager should not crash
    assert payload["status"] == "error"
    assert manager.is_running, "Manager should still be running after error"
    print(f"\n✓ invalid URL handled gracefully: {payload['error']['message'][:80]}")
