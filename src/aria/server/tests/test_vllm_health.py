"""Tests for _wait_for_ready() health polling in server/vllm.py."""

from unittest.mock import MagicMock, patch

from aria.server.vllm import VllmServerManager


def _make_manager() -> VllmServerManager:
    with patch("aria.server.vllm.load_state", return_value={}):
        return VllmServerManager()


class TestWaitForReady:
    """Tests for VllmServerManager._wait_for_ready()."""

    def test_returns_true_on_first_successful_poll(self):
        """Should return True immediately when /health responds 200."""
        manager = _make_manager()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("aria.server.vllm.urlopen", return_value=mock_resp):
            result = manager._wait_for_ready("127.0.0.1", 9090, timeout=5.0)

        assert result is True

    def test_returns_true_after_retry(self):
        """Should return True after a failed poll followed by a successful one."""
        manager = _make_manager()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def _urlopen_side_effect(url, timeout):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("connection refused")
            return mock_resp

        with (
            patch("aria.server.vllm.urlopen", side_effect=_urlopen_side_effect),
            patch("aria.server.vllm.time.sleep"),
        ):
            result = manager._wait_for_ready("127.0.0.1", 9090, timeout=10.0)

        assert result is True

    def test_returns_false_on_timeout(self):
        """Should return False when the server never becomes ready."""
        manager = _make_manager()

        from urllib.error import URLError

        with (
            patch("aria.server.vllm.urlopen", side_effect=URLError("refused")),
            patch("aria.server.vllm.time.sleep"),
            patch(
                "aria.server.vllm.time.time",
                side_effect=[
                    0.0,
                    0.5,
                    1.0,
                    1.5,
                    2.0,
                    2.1,
                ],  # deadline exceeded
            ),
        ):
            result = manager._wait_for_ready("127.0.0.1", 9090, timeout=2.0)

        assert result is False

    def test_uses_correct_url(self):
        """Health check URL must be http://<host>:<port>/health."""
        manager = _make_manager()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("aria.server.vllm.urlopen", return_value=mock_resp) as mock_open:
            manager._wait_for_ready("0.0.0.0", 7070, timeout=5.0)

        mock_open.assert_called_once_with("http://0.0.0.0:7070/health", timeout=2)
