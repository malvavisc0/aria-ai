"""Extras CLI — discover available CLI tools in the virtual environment.

Scans the active venv's bin directory for user-facing CLI binaries,
filters out internal/excluded entries, and returns a formatted markdown
table that can be injected into agent instructions at runtime.
"""

import fnmatch
import os
import shutil
import sys
from pathlib import Path

# Binaries to exclude — internal, unsafe, or not useful for agents.
_EXCLUDED_BINARIES: set[str] = {
    # Python internals
    "activate",
    "activate.bat",
    "activate.csh",
    "activate.fish",
    "activate.nu",
    "activate.ps1",
    "activate_this.py",
    "deactivate.bat",
    "blackd",
    "python",
    "python3",
    "python3.12",
    "pydoc.bat",
    # Aria internals
    "aria",
    "aria-gui",
    "ax",
    # AI
    "huggingface-cli",
    # Package managers / build internals
    "pip",
    "pip3",
    "pip3.12",
    "wheel",
    "distlib",
    "distlib-script",
    "setuptools",
    "pkg_resources",
    # PyInstaller internals
    "pyi-archive_viewer",
    "pyi-bindepend",
    "pyi-grab_version",
    "pyi-makespec",
    "pyi-set_version",
    "pyinstaller",
    # Supervisor internals
    "echo_supervisord_conf",
    "generate-supervisor-config",
    "pidproxy",
    "standard-supervisor",
    # Misc internals / not useful standalone
    "cbor2",
    "chainlit",
    "chevron",
    "chroma",
    "coverage",
    "coverage3",
    "coverage-3.12",
    "curl-cffi",
    "deactivate",
    "distro",
    "dotenv",
    "f2py",
    "flashinfer",
    "get_gprof",
    "get_objgraph",
    "gguf-editor-gui",
    "griffecli",
    "isort-identify-imports",
    "isympy",
    "jp.py",
    "json-playground",
    "llama-index-instrumentation",
    "mistral_common",
    "normalizer",
    "nltk",
    "numba",
    "numpy-config",
    "onnxruntime_test",
    "opentelemetry-bootstrap",
    "opentelemetry-instrument",
    "proton-viewer",
    "pypdfium2",
    "py.test",
    "pybase64",
    "pycodestyle",
    "pyflakes",
    "pygmentize",
    "sample",
    "striprtf",
    "supervisorctl",
    "supervisord",
    "tabulate",
    "torchfrtrace",
    "torchrun",
    "tqdm",
    "tvm-ffi-config",
    "tvm-ffi-stubgen",
    "typer",
    "undill",
    "uvicorn",
    "watchfiles",
    "wsdump",
    "llama-parse",
    "llamaindex-cli",
    "markdown-it",
    "markdownify",
    "pre-commit",
}

# Glob patterns for excluded binaries (e.g. "pyside6*" excludes all pyside6-* binaries).
_EXCLUDED_PATTERNS: set[str] = {"pyside6*", "gguf-*"}

# Binaries that require external dependencies to be useful.
# If the dependency is not found on PATH, the binary is excluded.
_DEPENDENCY_CHECKS: dict[str, list[str]] = {
    "tiny-agents": ["npx"],
}

# Category groupings for display.
_CATEGORIES: dict[str, list[str]] = {
    "AI": [
        "hf",
        "huggingface-cli",
        "openai",
        "transformers",
        "tiny-agents",
        "llamaindex-cli",
        "llama-parse",
        "vllm",
        "mcp",
        "torchrun",
        "numba",
        "flashinfer",
    ],
    "Web": [
        "httpx",
        "fastapi",
        "uvicorn",
        "playwright",
        "websockets",
    ],
    "Search": [
        "webserp",
        "markitdown",
        "markdownify",
        "markdown-it",
        "magika",
        "youtube_transcript_api",
        "filetype",
    ],
    "Linting": [
        "black",
        "blackd",
        "ruff",
        "flake8",
        "isort",
    ],
    "Data": [
        "jsonschema",
        "pwiz",
        "gguf-convert-endian",
        "gguf-dump",
        "gguf-editor-gui",
        "gguf-new-metadata",
        "gguf-set-metadata",
    ],
    "Build": [
        "ninja",
        "pyproject-build",
        "griffe",
    ],
    "NLP": [
        "nltk",
    ],
    "System": [
        "cpuinfo",
        "distro",
        "tqdm",
        "chainlit",
        "supervisorctl",
        "supervisord",
        "z3",
        "typer",
    ],
}


def _is_excluded(name: str, excluded: set[str], patterns: set[str]) -> bool:
    """Check if a binary name should be excluded via exact match or glob pattern."""
    if name in excluded:
        return True
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _get_venv_bin_dir() -> Path | None:
    """Return the venv bin directory, or None if not in a venv."""
    # Check VIRTUAL_ENV env var first (most reliable when activated)
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        return Path(venv) / "bin"
    # Fallback: sys.prefix / bin (works when running from venv python)
    candidate = Path(sys.prefix) / "bin"
    if candidate.exists():
        return candidate
    return None


def _get_aria_bin_dir() -> Path | None:
    """Return the ~/.aria/bin directory, or None if not available."""
    try:
        from aria.config.folders import Bin

        bin_path = Bin.path
        if bin_path.exists():
            return bin_path
    except Exception:
        pass
    return None


def get_venv_extras(
    excluded: set[str] | None = None,
    filter_term: str | None = None,
) -> str:
    """Scan the venv bin directory and return a formatted markdown table.

    Args:
        excluded: Additional binaries to exclude beyond the default set.
        filter_term: If provided, only include binaries matching this substring.

    Returns:
        A markdown string with the extras table, or a message if no venv found.
    """
    bin_dir = _get_venv_bin_dir()
    if not bin_dir or not bin_dir.exists():
        return "No virtual environment detected."

    all_excluded = _EXCLUDED_BINARIES | (excluded or set())
    all_patterns = _EXCLUDED_PATTERNS

    # Collect available binaries
    available: set[str] = set()
    for entry in sorted(bin_dir.iterdir()):
        name = entry.name
        if _is_excluded(name, all_excluded, all_patterns):
            continue
        if not entry.is_file():
            continue
        # Skip non-executable (but allow all on systems where everything is +x)
        if not os.access(entry, os.X_OK):
            continue
        # Skip .bat/.csh files
        if name.endswith((".bat", ".csh", ".fish", ".nu", ".ps1")):
            continue
        # Check dependency requirements
        if name in _DEPENDENCY_CHECKS:
            deps = _DEPENDENCY_CHECKS[name]
            if not all(shutil.which(d) for d in deps):
                continue
        if filter_term and filter_term.lower() not in name.lower():
            continue
        available.add(name)

    if not available:
        return "No extra CLI tools found in the virtual environment."

    # Build categorized table
    categorized: set[str] = set()
    rows: list[tuple[str, str]] = []

    for category, members in _CATEGORIES.items():
        found = [m for m in members if m in available]
        if not found:
            continue
        categorized.update(found)
        rows.append((category, "`, `".join(sorted(found))))

    # Uncategorized binaries
    uncategorized = sorted(available - categorized)
    if uncategorized:
        rows.append(("Other", "`, `".join(uncategorized)))

    lines: list[str] = []

    # Scan ~/.aria/bin for Aria-managed binaries
    aria_bin_dir = _get_aria_bin_dir()
    if aria_bin_dir:
        aria_bins = sorted(
            f.name
            for f in aria_bin_dir.iterdir()
            if f.is_file() and os.access(f, os.X_OK) and not f.name.startswith(".")
        )
        if aria_bins:
            lines.append("### Aria-Managed Binaries\n")
            lines.append(
                f"The binaries are installed in `{aria_bin_dir}` are "
                "automatically on $PATH. They will be available on PATH for all shell commands"
            )
            lines.append("")
            lines.append(
                f"Download and/or additional binaries to `{aria_bin_dir}`: download → `chmod +x` → verify. Shared across agents."
            )
            lines.append("")

    lines.append("### Virtual Environment Commands\n")
    lines.append(
        "You can use these commands in your active virtual environment by calling them with `shell`. "
        "Use them when your registered tools aren't enough to get the job done.\n"
    )
    lines.append(
        "| Category | Commands |",
    )
    lines.append(
        "|----------|----------|",
    )
    for category, commands in rows:
        lines.append(f"| {category} | `{commands}` |")

    lines.append("")
    lines.append(
        "Always run `<command> --help` before using any new command for the first time."
    )

    return "\n".join(lines)


def get_venv_extras_list(
    excluded: set[str] | None = None,
    filter_term: str | None = None,
) -> list[str]:
    """Return just the binary names as a sorted list."""
    bin_dir = _get_venv_bin_dir()
    if not bin_dir or not bin_dir.exists():
        return []

    all_excluded = _EXCLUDED_BINARIES | (excluded or set())
    all_patterns = _EXCLUDED_PATTERNS
    available: list[str] = []
    for entry in sorted(bin_dir.iterdir()):
        name = entry.name
        if _is_excluded(name, all_excluded, all_patterns):
            continue
        if not entry.is_file():
            continue
        if not os.access(entry, os.X_OK):
            continue
        if name.endswith((".bat", ".csh", ".fish", ".nu", ".ps1")):
            continue
        # Check dependency requirements
        if name in _DEPENDENCY_CHECKS:
            deps = _DEPENDENCY_CHECKS[name]
            if not all(shutil.which(d) for d in deps):
                continue
        if filter_term and filter_term.lower() not in name.lower():
            continue
        available.append(name)
    return available


def get_venv_extras_json(
    reason: str = "",
    excluded: set[str] | None = None,
    filter_term: str | None = None,
) -> dict:
    """Return extras as a structured dict for JSON serialization.

    Returns:
        A dict with ``categories``, ``uncategorized``, and ``total`` keys.
    """
    bin_dir = _get_venv_bin_dir()
    if not bin_dir or not bin_dir.exists():
        return {"categories": {}, "uncategorized": [], "total": 0}

    all_excluded = _EXCLUDED_BINARIES | (excluded or set())
    all_patterns = _EXCLUDED_PATTERNS

    # Collect available binaries
    available: set[str] = set()
    for entry in sorted(bin_dir.iterdir()):
        name = entry.name
        if _is_excluded(name, all_excluded, all_patterns):
            continue
        if not entry.is_file():
            continue
        if not os.access(entry, os.X_OK):
            continue
        if name.endswith((".bat", ".csh", ".fish", ".nu", ".ps1")):
            continue
        if name in _DEPENDENCY_CHECKS:
            deps = _DEPENDENCY_CHECKS[name]
            if not all(shutil.which(d) for d in deps):
                continue
        if filter_term and filter_term.lower() not in name.lower():
            continue
        available.add(name)

    # Build categorized result
    categorized: set[str] = set()
    categories: dict[str, list[str]] = {}
    for category, members in _CATEGORIES.items():
        found = sorted(m for m in members if m in available)
        if not found:
            continue
        categorized.update(found)
        categories[category] = found

    uncategorized = sorted(available - categorized)

    return {
        "categories": categories,
        "uncategorized": uncategorized,
        "total": len(available),
    }
