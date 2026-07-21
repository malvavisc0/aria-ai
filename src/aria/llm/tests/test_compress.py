"""Tests for the tool output compression module."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_env_and_cache(monkeypatch: pytest.MonkeyPatch):
    """Remove any ARIA_COMPRESS_* env vars and clear threshold cache."""
    from aria.llm._compress import _reset_threshold_cache

    _reset_threshold_cache()
    for key in [
        "ARIA_COMPRESS_MIN_RATIO",
        "ARIA_COMPRESS_MAX_RATIO",
        "ARIA_COMPRESS_HEAD_RATIO",
        "ARIA_COMPRESS_TAIL_RATIO",
        "ARIA_COMPRESS_AGGRESSIVE_HEAD_RATIO",
        "ARIA_COMPRESS_AGGRESSIVE_TAIL_RATIO",
        "ARIA_COMPRESS_MIN_CHARS",
        "ARIA_COMPRESS_MAX_CHARS",
        "ARIA_COMPRESS_HEAD_CHARS",
        "ARIA_COMPRESS_TAIL_CHARS",
        "ARIA_COMPRESS_AGGRESSIVE_HEAD",
        "ARIA_COMPRESS_AGGRESSIVE_TAIL",
        "ARIA_SCRATCHPAD_PRESSURE_THRESHOLD",
    ]:
        monkeypatch.delenv(key, raising=False)
    # Force 32K context so tests with hardcoded 32K thresholds are stable.
    # _get_context_size() checks CHAT_CONTEXT_SIZE env first, then
    # VllmConfig; setting the env here ensures consistent test behavior.
    monkeypatch.setenv("CHAT_CONTEXT_SIZE", "32768")
    _reset_threshold_cache()
    yield
    _reset_threshold_cache()


def _reload_compress():
    """Re-import _compress so it picks up env changes from monkeypatch."""
    from aria.llm._compress import _reset_threshold_cache

    _reset_threshold_cache()
    import aria.llm._compress as mod

    importlib.reload(mod)
    mod._reset_threshold_cache()
    return mod


# ---------------------------------------------------------------------------
# Tests using the 32K default context (CHART_CONTEXT_SIZE not set)
# ---------------------------------------------------------------------------


class TestComputeThresholds:
    """Tests for _compute_thresholds()."""

    def test_32k_context(self):
        from aria.llm._compress import _compute_thresholds

        t = _compute_thresholds(32768)
        # 32768 tokens × 4 chars/token = 131072 chars
        # min  = 0.5% → 655
        # max  = 2.5% → 3276
        # head = 0.5% → 655
        # tail = 0.2% → 262
        # agg_head = 0.2% → 262
        # agg_tail = 0.1% → 131
        assert t["min_chars"] == 655
        assert t["max_chars"] == 3276
        assert t["head_chars"] == 655
        assert t["tail_chars"] == 262
        assert t["aggressive_head"] == 262
        assert t["aggressive_tail"] == 131

    def test_262k_context(self):
        from aria.llm._compress import _compute_thresholds

        t = _compute_thresholds(262144)
        # 262144 × 4 = 1048576 chars
        # min  = 0.5% → 5242
        # max  = 2.5% → 26214
        # head = 0.5% → 5242
        # tail = 0.2% → 2097
        assert t["min_chars"] == 5242
        assert t["max_chars"] == 26214
        assert t["head_chars"] == 5242
        assert t["tail_chars"] == 2097

    def test_128k_context(self):
        from aria.llm._compress import _compute_thresholds

        t = _compute_thresholds(131072)
        # 131072 × 4 = 524288 chars
        # min = 0.5% → 2621
        assert t["min_chars"] == 2621


class TestCompressToolOutput:
    """Tests for compress_tool_output() using default 32K context."""

    def test_empty_string(self):
        from aria.llm._compress import compress_tool_output

        assert compress_tool_output("") == ""

    def test_below_min_passes_through(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        text = "x" * (t["min_chars"] - 1)
        result = compress_tool_output(text)
        assert result is text  # identity — no copy

    def test_exactly_at_min_passes_through(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        text = "x" * t["min_chars"]
        result = compress_tool_output(text)
        assert result is text

    def test_just_above_min_gets_compressed(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        # Build text large enough that head + notice + tail < original.
        # Notice is ~120 chars, so we need text > head + 120 + tail.
        text_size = t["min_chars"] + t["head_chars"] + t["tail_chars"] + 200
        assert text_size <= t["max_chars"]
        head = "a" * t["head_chars"]
        tail = "b" * t["tail_chars"]
        middle = "M" * (text_size - t["head_chars"] - t["tail_chars"])
        text = head + middle + tail

        result = compress_tool_output(text, tool_name="test_tool")
        assert len(result) < len(text)
        assert result.startswith("a" * t["head_chars"])
        assert result.endswith("b" * t["tail_chars"])
        assert "compressed" in result

    def test_medium_compression_preserves_head_and_tail(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        # Build text in medium range (min < size ≤ max)
        text_size = t["min_chars"] + 500
        assert text_size <= t["max_chars"]
        head = "H" * t["head_chars"]
        tail = "T" * t["tail_chars"]
        middle = "M" * (text_size - t["head_chars"] - t["tail_chars"])
        text = head + middle + tail

        result = compress_tool_output(text)
        assert result.startswith("H" * t["head_chars"])
        assert result.endswith("T" * t["tail_chars"])
        assert "compressed" in result
        assert "heavily" not in result

    def test_large_compression_uses_aggressive_thresholds(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        text = "X" * (t["max_chars"] + 500)
        result = compress_tool_output(text)

        assert result.startswith("X" * t["aggressive_head"])
        assert result.endswith("X" * t["aggressive_tail"])
        assert "heavily compressed" in result

    def test_compression_notice_includes_original_size(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        text = "Y" * (t["max_chars"] + 1000)
        result = compress_tool_output(text)

        original_size = t["max_chars"] + 1000
        assert f"{original_size:,}" in result

    def test_compression_notice_suggests_smaller_chunks(self):
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        text = "Z" * (t["max_chars"] + 100)
        result = compress_tool_output(text)

        assert "offset/length" in result or "max_results" in result


class TestScratchpadPressureThreshold:
    """Tests for the SCRATCHPAD_PRESSURE_THRESHOLD constant."""

    def test_default_threshold(self):
        from aria.llm._compress import SCRATCHPAD_PRESSURE_THRESHOLD

        assert SCRATCHPAD_PRESSURE_THRESHOLD == 0.40

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARIA_SCRATCHPAD_PRESSURE_THRESHOLD", "0.60")
        mod = _reload_compress()
        assert mod.SCRATCHPAD_PRESSURE_THRESHOLD == 0.60

    def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARIA_SCRATCHPAD_PRESSURE_THRESHOLD", "not-a-number")
        mod = _reload_compress()
        assert mod.SCRATCHPAD_PRESSURE_THRESHOLD == 0.40


class TestRatioOverrides:
    """Tests that ratio env vars override defaults."""

    def test_min_ratio_override(self, monkeypatch: pytest.MonkeyPatch):

        monkeypatch.setenv("ARIA_COMPRESS_MIN_RATIO", "0.01")
        mod = _reload_compress()
        t = mod._compute_thresholds(32768)
        # 1% of 131072 = 1310
        assert t["min_chars"] == 1310

    def test_max_ratio_override(self, monkeypatch: pytest.MonkeyPatch):

        monkeypatch.setenv("ARIA_COMPRESS_MAX_RATIO", "0.05")
        mod = _reload_compress()
        t = mod._compute_thresholds(32768)
        # 5% of 131072 = 6553
        assert t["max_chars"] == 6553


class TestAbsoluteOverrides:
    """Tests that absolute env vars take precedence over ratios."""

    def test_absolute_min_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARIA_COMPRESS_MIN_CHARS", "100")
        mod = _reload_compress()
        t = mod._compute_thresholds(32768)
        assert t["min_chars"] == 100

    def test_absolute_max_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARIA_COMPRESS_MAX_CHARS", "5000")
        mod = _reload_compress()
        t = mod._compute_thresholds(32768)
        assert t["max_chars"] == 5000

    def test_absolute_overrides_all_ratios(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARIA_COMPRESS_MIN_CHARS", "10")
        monkeypatch.setenv("ARIA_COMPRESS_MAX_CHARS", "200")
        monkeypatch.setenv("ARIA_COMPRESS_HEAD_CHARS", "50")
        monkeypatch.setenv("ARIA_COMPRESS_TAIL_CHARS", "30")
        monkeypatch.setenv("ARIA_COMPRESS_AGGRESSIVE_HEAD", "20")
        monkeypatch.setenv("ARIA_COMPRESS_AGGRESSIVE_TAIL", "10")
        mod = _reload_compress()
        t = mod._compute_thresholds(32768)
        assert t["min_chars"] == 10
        assert t["max_chars"] == 200
        assert t["head_chars"] == 50
        assert t["tail_chars"] == 30
        assert t["aggressive_head"] == 20
        assert t["aggressive_tail"] == 10

    def test_absolute_min_compresses_small_output(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("ARIA_COMPRESS_MIN_CHARS", "100")
        monkeypatch.setenv("ARIA_COMPRESS_HEAD_CHARS", "30")
        monkeypatch.setenv("ARIA_COMPRESS_TAIL_CHARS", "20")
        mod = _reload_compress()

        # head(30) + notice(~130) + tail(20) ≈ 180, so need text > 180
        text = "x" * 300
        result = mod.compress_tool_output(text, "test")
        assert "compressed" in result


class TestOverlapGuard:
    """Tests that head+tail overlap doesn't produce negative 'dropped'."""

    def test_medium_overlap_returns_original(self):
        """When head + tail >= length, compression skips."""
        from aria.llm._compress import (
            compress_tool_output,
        )

        # Create text where head + tail >= length but length > min_chars
        # min=655, head=655, tail=262 → head+tail=917
        # So a 918-char text just barely exceeds min but head+tail > length
        text = "x" * 918
        result = compress_tool_output(text)
        assert result is text  # should pass through unchanged

    def test_negative_dropped_never_happens(self):
        """The 'dropped' count in the notice is never negative."""
        from aria.llm._compress import (
            _compute_thresholds,
            compress_tool_output,
        )

        t = _compute_thresholds(32768)
        # Test across the full range from min to max
        for size in [
            t["min_chars"] + 1,
            (t["min_chars"] + t["max_chars"]) // 2,
            t["max_chars"] - 1,
            t["max_chars"],
            t["max_chars"] + 1000,
        ]:
            text = "y" * size
            result = compress_tool_output(text)
            if result is not text:
                # Extract dropped count from notice
                import re

                match = re.search(r"dropped ([\d,]+) chars", result)
                if match:
                    dropped = int(match.group(1).replace(",", ""))
                    assert dropped >= 0, f"Negative dropped ({dropped}) for size {size}"


class TestContextScaling:
    """Tests that thresholds scale correctly with context size."""

    def test_262k_min_is_bigger_than_32k_min(self):
        from aria.llm._compress import _compute_thresholds

        t32 = _compute_thresholds(32768)
        t262 = _compute_thresholds(262144)
        # 262K min should be ~8× bigger than 32K min
        assert t262["min_chars"] > t32["min_chars"] * 4

    def test_thresholds_scale_with_context(self):
        """Verify that compression boundaries scale proportionally."""
        from aria.llm._compress import _compute_thresholds

        t32 = _compute_thresholds(32768)
        t262 = _compute_thresholds(262144)
        t131 = _compute_thresholds(131072)

        # All thresholds should scale proportionally with context
        for key in [
            "min_chars",
            "max_chars",
            "head_chars",
            "tail_chars",
            "aggressive_head",
            "aggressive_tail",
        ]:
            assert t131[key] > t32[key], f"{key} should grow with context"
            assert t262[key] > t131[key], f"{key} should grow with context"
            # Verify proportionality (within rounding)
            ratio_262_32 = t262[key] / t32[key]
            assert 7.5 < ratio_262_32 < 8.5, (
                f"{key}: 262K/32K ratio should be ~8×, got {ratio_262_32}"
            )
