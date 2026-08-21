"""Preflight checks for the Aria web UI.

Verifies that all required dependencies are in place before starting
the Chainlit web server:
  - Required environment variables are set
  - Data folder exists
  - vLLM is installed (Python package)
  - All required models are configured (chat, embeddings)
  - Model paths exist (local dirs or HF snapshots)

Example:
    ```python
    from aria.preflight import run_preflight_checks

    result = run_preflight_checks()
    if not result.passed:
        for failure in result.failures:
            print(f"Missing: {failure.error}")
            print(f"Fix: {failure.hint}")
    ```
"""

from aria.preflight.checks_basic import (
    REQUIRED_ENV_VARS,
    _check_binaries,
    _check_data_folder,
    _check_docling,
    _check_env_vars,
    _check_lightpanda,
    _check_vision,
    _check_voice,
)
from aria.preflight.checks_hardware import (
    _check_kv_cache_memory,
    _check_memory_requirements,
)
from aria.preflight.checks_models import (
    _check_models,
    _check_token_limit,
)
from aria.preflight.checks_runtime import (
    _check_llm_server,
    _check_memory_db,
    _check_tool_loading,
)
from aria.preflight.results import CheckResult, PreflightResult

__all__ = [
    "REQUIRED_ENV_VARS",
    "CheckResult",
    "PreflightResult",
    "run_preflight_checks",
]


def run_preflight_checks() -> PreflightResult:
    """Run all preflight checks required before starting the web UI.

    Checks performed (all run before returning so every failure is reported):
        1. All required environment variables are set
        2. Data folder exists
        3. vLLM is installed
        4. Lightpanda is installed
        5. Docling worker is installed
        6. Voice components (whisper.cpp STT + kokoro TTS) are installed
           (skipped when ARIA_VOICE_ENABLED=false)
        7. Vision (image upload) state — informational, never blocks
        8. Chat model is configured and downloaded
        9. Embeddings model is configured and downloaded
       10. Token limit is within context bounds
       11. Memory requirements fit available hardware
       12. LLM server connectivity (informational)
       13. Knowledge database access
       14. Tool loading

    Returns:
        PreflightResult with pass/fail status and all check details.
    """
    checks: list[CheckResult] = []

    _check_env_vars(checks)
    _check_data_folder(checks)
    _check_binaries(checks)
    _check_lightpanda(checks)
    _check_docling(checks)
    _check_voice(checks)
    _check_vision(checks)
    _check_models(checks)
    _check_token_limit(checks)
    _check_memory_requirements(checks)
    _check_kv_cache_memory(checks)
    _check_llm_server(checks)
    _check_memory_db(checks)
    _check_tool_loading(checks)

    return PreflightResult(
        passed=all(c.passed for c in checks),
        checks=checks,
    )
