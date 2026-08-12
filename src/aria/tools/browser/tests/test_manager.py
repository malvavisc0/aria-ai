"""Tests for browser manager response helpers and recovery behavior."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from aria.tools.browser.manager import LightpandaManager


def _make_manager() -> LightpandaManager:
    """Create a manager with a placeholder binary path for unit tests."""
    return LightpandaManager(Path("/tmp/lightpanda"))


def test_is_running_false_when_not_started() -> None:
    manager = _make_manager()
    assert manager.is_running is False


def test_is_running_true_when_all_set() -> None:
    manager = _make_manager()
    manager._process = Mock()
    manager._browser = Mock()
    manager._page = Mock()
    assert manager.is_running is True


def test_success_uses_standard_envelope() -> None:
    manager = _make_manager()

    ok_payload = json.loads(
        manager._success({"key": "val"}, tool="test_tool", reason="testing")
    )
    assert ok_payload["status"] == "success"
    assert ok_payload["tool"] == "test_tool"
    assert ok_payload["reason"] == "testing"
    assert "timestamp" in ok_payload
    assert ok_payload["data"] == {"key": "val"}


def test_error_uses_standard_envelope() -> None:
    manager = _make_manager()

    err_payload = json.loads(
        manager._error("boom", recovery=True, tool="test_tool", reason="testing")
    )
    assert err_payload["status"] == "error"
    assert err_payload["tool"] == "test_tool"
    assert err_payload["reason"] == "testing"
    assert "timestamp" in err_payload
    assert err_payload["error"]["message"] == "boom"
    assert err_payload["error"]["recoverable"] is True
    assert err_payload["error"]["how_to_fix"] == ("Browser crashed. Restarted. Retry.")


def test_error_without_recovery() -> None:
    manager = _make_manager()
    payload = json.loads(manager._error("something broke", tool="t", reason="i"))
    assert payload["status"] == "error"
    assert payload["error"]["message"] == "something broke"
    assert payload["error"]["recoverable"] is False
    assert "how_to_fix" not in payload["error"]


@pytest.mark.asyncio
async def test_with_recovery_returns_error_when_page_unavailable() -> None:
    manager = _make_manager()
    manager._ensure_page = AsyncMock(return_value=False)

    result = await manager._with_recovery(
        "test", AsyncMock(return_value="ok"), tool="t", reason="i"
    )
    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["error"]["message"] == "Browser not available"


@pytest.mark.asyncio
async def test_with_recovery_calls_fn_on_valid_page() -> None:
    manager = _make_manager()
    page = Mock()
    manager._page = page
    manager._ensure_page = AsyncMock(return_value=True)

    fn = AsyncMock(return_value='{"ok": true}')
    result = await manager._with_recovery("test", fn)

    fn.assert_awaited_once_with(page)
    assert result == '{"ok": true}'


@pytest.mark.asyncio
async def test_with_recovery_returns_recovery_error_on_crash() -> None:
    manager = _make_manager()
    page = Mock()
    manager._page = page
    manager._ensure_page = AsyncMock(side_effect=[True, True])
    manager._is_page_valid = Mock(return_value=False)

    fn = AsyncMock(side_effect=Exception("crashed"))
    result = await manager._with_recovery("test", fn, tool="t", reason="i")
    payload = json.loads(result)

    assert payload["status"] == "error"
    assert payload["error"]["message"] == "crashed"
    assert payload["error"]["recoverable"] is True
    assert payload["error"]["how_to_fix"] == ("Browser crashed. Restarted. Retry.")


@pytest.mark.asyncio
async def test_with_recovery_returns_plain_error_when_page_still_valid() -> None:
    manager = _make_manager()
    page = Mock()
    manager._page = page
    manager._ensure_page = AsyncMock(return_value=True)
    manager._is_page_valid = Mock(return_value=True)

    fn = AsyncMock(side_effect=Exception("timeout"))
    result = await manager._with_recovery("test", fn, tool="t", reason="i")
    payload = json.loads(result)

    assert payload["status"] == "error"
    assert "timeout" in payload["error"]["message"]
    assert "download tool" in payload["error"]["message"]
    assert payload["error"]["recoverable"] is False


@pytest.mark.asyncio
async def test_navigate_returns_recovery_error_after_crash() -> None:
    manager = _make_manager()
    page = Mock()
    page.url = "https://example.com"
    page.goto = AsyncMock(side_effect=Exception("nav failed"))
    page.wait_for_load_state = AsyncMock()
    page.title = AsyncMock(return_value="Example")

    manager._process = Mock()
    manager._browser = Mock()
    manager._page = page

    # _ensure_page succeeds initially; after crash _is_page_valid returns
    # False so _with_recovery enters the crash-recovery branch, then
    # _ensure_page succeeds again for the restart.
    manager._is_page_valid = Mock(return_value=False)
    manager._ensure_page = AsyncMock(side_effect=[True, True])

    result = await manager.navigate(
        "https://example.com", tool="visit_url", reason="testing"
    )
    payload = json.loads(result)

    assert payload["status"] == "error"
    assert payload["error"]["message"] == "nav failed"
    assert payload["error"]["recoverable"] is True


@pytest.mark.asyncio
async def test_click_returns_recovery_error_after_crash() -> None:
    manager = _make_manager()
    page = Mock()
    page.url = "https://example.com"
    page.click = AsyncMock(side_effect=Exception("click failed"))
    page.wait_for_load_state = AsyncMock()
    page.title = AsyncMock(return_value="Example")

    manager._process = Mock()
    manager._browser = Mock()
    manager._page = page

    # _ensure_page succeeds initially; after crash _is_page_valid returns
    # False so _with_recovery enters the crash-recovery branch.
    manager._is_page_valid = Mock(return_value=False)
    manager._ensure_page = AsyncMock(side_effect=[True, True])

    result = await manager.click(
        "button.accept", tool="browser_click", reason="testing"
    )
    payload = json.loads(result)

    assert payload["status"] == "error"
    assert payload["error"]["message"] == "click failed"
    assert payload["error"]["recoverable"] is True


def test_navigation_failed_on_empty_content() -> None:
    assert LightpandaManager._is_navigation_failed("", "https://example.com")
    assert LightpandaManager._is_navigation_failed("   ", "https://example.com")


def test_navigation_failed_on_about_blank() -> None:
    assert LightpandaManager._is_navigation_failed("some content", "about:blank")


def test_navigation_failed_on_error_patterns() -> None:
    assert LightpandaManager._is_navigation_failed(
        "Navigation failed", "https://example.com"
    )
    assert LightpandaManager._is_navigation_failed(
        "net::ERR_CONNECTION_REFUSED", "https://example.com"
    )


def test_navigation_not_failed_on_valid_content() -> None:
    assert not LightpandaManager._is_navigation_failed(
        "Hello World", "https://example.com"
    )


def test_persist_content_writes_file(tmp_path: Path) -> None:
    manager = _make_manager()

    with patch(
        "aria.tools.browser.manager._build_content_filepath",
        return_value=tmp_path / "test.txt",
    ):
        path = manager._persist_content("hello", "https://example.com", "open")

    assert path.exists()
    assert path.read_text() == "hello"
