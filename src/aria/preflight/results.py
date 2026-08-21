"""Preflight result types shared by all checks."""

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """Result of a single preflight check.

    Attributes:
        name: Short name of the check (e.g. "vLLM package").
        passed: True if the check passed, False otherwise.
        category: Group for display (environment, storage, binaries, models, hardware).
        error: Human-readable description of what is missing (if failed).
        hint: Remediation command or instruction for the user (if failed).
        details: Optional extra info to display on success (e.g. "24 GB available").
        warning: True for a non-blocking degradation (passed is still True,
            but the UI should render it as a warning, not a clean pass).
        informational: True for a purely informational note that is neither a
            pass nor a failure (e.g. a feature disabled by config). The UI
            renders it with a neutral icon; it never blocks or offers install.
    """

    name: str
    passed: bool
    category: str = "general"
    error: str = ""
    hint: str = ""
    details: str = ""
    warning: bool = False
    informational: bool = False


@dataclass
class PreflightResult:
    """Result of running all preflight checks.

    Attributes:
        passed: True if all checks passed, False if any failed.
        checks: List of all CheckResult instances.
        failures: List of failed CheckResult instances.
    """

    passed: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        """Return only the failed checks."""
        return [c for c in self.checks if not c.passed]

    def group_by_category(self) -> dict[str, list[CheckResult]]:
        """Group checks by category for display.

        Returns:
            Dict mapping category names to lists of checks.
        """
        grouped: dict[str, list[CheckResult]] = {}
        for check in self.checks:
            if check.category not in grouped:
                grouped[check.category] = []
            grouped[check.category].append(check)
        return grouped
