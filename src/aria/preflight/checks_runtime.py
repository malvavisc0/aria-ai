"""Runtime preflight checks: connectivity, databases, and tool loading."""

from aria.preflight.results import CheckResult


def _check_llm_server(checks: list[CheckResult]) -> None:
    """Check that the LLM server is reachable (non-blocking).

    The LLM server starts *after* preflight, so this check always passes.
    It reports connectivity status as details/warning for informational purposes.
    """
    try:
        import httpx

        from aria.config.api import Vllm as VllmConfig
        from aria.config.models import Chat as ChatConfig

        headers = {}
        if VllmConfig.remote and VllmConfig.api_key:
            headers["Authorization"] = f"Bearer {VllmConfig.api_key}"
        r = httpx.get(f"{ChatConfig.api_url}/models", timeout=3, headers=headers)
        models = r.json().get("data", [])
        checks.append(
            CheckResult(
                name="LLM server",
                passed=True,
                category="connectivity",
                details=(f"{ChatConfig.api_url} ({len(models)} model(s))"),
            )
        )
    except Exception:
        # Non-blocking: server starts after preflight
        checks.append(
            CheckResult(
                name="LLM server",
                passed=True,
                category="connectivity",
                details="Not running yet (will start with server)",
            )
        )


def _check_memory_db(checks: list[CheckResult]) -> None:
    """Check that the memory database is accessible."""
    try:
        from aria.tools.memory.database import MemoryDatabase

        MemoryDatabase()
        checks.append(
            CheckResult(
                name="Memory DB",
                passed=True,
                category="storage",
                details="SQLite accessible",
            )
        )
    except Exception as e:
        checks.append(
            CheckResult(
                name="Memory DB",
                passed=False,
                category="storage",
                error=str(e),
                hint="Check ARIA_HOME and ARIA_DB_FILENAME in .env",
            )
        )


def _check_tool_loading(checks: list[CheckResult]) -> None:
    """Check that core + file tools load correctly."""
    try:
        from aria.tools.registry import CORE, FILES, get_tools

        tools = get_tools([CORE, FILES])
        checks.append(
            CheckResult(
                name="Tool loading",
                passed=True,
                category="tools",
                details=f"{len(tools)} tools loaded",
            )
        )
    except Exception as e:
        checks.append(
            CheckResult(
                name="Tool loading",
                passed=False,
                category="tools",
                error=str(e),
                hint="Check tool dependencies are installed",
            )
        )
