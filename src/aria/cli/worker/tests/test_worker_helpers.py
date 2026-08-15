"""Tests for worker CLI helper functions."""

from aria.cli.worker import _audit_path, _output_dir


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
