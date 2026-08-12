"""Tests for worker CLI helper functions."""

from aria.cli.worker import _audit_path, _output_dir, _worker_id


class TestWorkerId:
    """Test worker ID generation."""

    def test_starts_with_worker_prefix(self):
        """Worker ID should start with 'worker_'."""
        wid = _worker_id()
        assert wid.startswith("worker_")

    def test_has_hex_suffix(self):
        """Worker ID should have 8-char hex suffix."""
        wid = _worker_id()
        suffix = wid.removeprefix("worker_")
        assert len(suffix) == 8
        # Should be valid hex
        int(suffix, 16)

    def test_ids_are_unique(self):
        """Multiple calls should produce unique IDs."""
        ids = {_worker_id() for _ in range(100)}
        assert len(ids) == 100


class TestAuditPath:
    """Test audit path generation."""

    def test_ends_with_json(self):
        """Audit path should end with .json."""
        path = _audit_path("worker_abc12345")
        assert path.name == "worker_abc12345.json"


class TestOutputDir:
    """Test output directory path generation."""

    def test_ends_with_worker_id(self):
        """Output dir should end with the worker ID."""
        path = _output_dir("worker_abc12345")
        assert path.name == "worker_abc12345"
