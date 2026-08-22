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
# Also excludes shell-script wrappers that aren't useful to agents.
_EXCLUDED_PATTERNS: set[str] = {
    "pyside6*",
    "gguf-*",
    "*.bat",
    "*.csh",
    "*.fish",
    "*.nu",
    "*.ps1",
}

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
    from aria.config.folders import Bin

    bin_path = Bin.path
    if bin_path.exists():
        return bin_path
    return None


def _scan_venv_binaries(
    bin_dir: Path,
    excluded: set[str],
    patterns: set[str],
    filter_term: str | None,
) -> set[str]:
    """Return the set of usable CLI binaries found in ``bin_dir``."""
    available: set[str] = set()
    for entry in sorted(bin_dir.iterdir()):
        name = entry.name
        if _is_excluded(name, excluded, patterns):
            continue
        if not entry.is_file() or not os.access(entry, os.X_OK):
            continue
        if name in _DEPENDENCY_CHECKS and not all(
            shutil.which(d) for d in _DEPENDENCY_CHECKS[name]
        ):
            continue
        if filter_term and filter_term.lower() not in name.lower():
            continue
        available.add(name)
    return available


def _categorize(available: set[str]) -> list[tuple[str, list[str]]]:
    """Group available binaries into ordered (category, members) rows."""
    rows: list[tuple[str, list[str]]] = []
    categorized: set[str] = set()
    for category, members in _CATEGORIES.items():
        found = sorted(m for m in members if m in available)
        if not found:
            continue
        categorized.update(found)
        rows.append((category, found))
    uncategorized = sorted(available - categorized)
    if uncategorized:
        rows.append(("Other", uncategorized))
    return rows


def _aria_managed_section(aria_bin_dir: Path | None) -> list[str]:
    """Build the Aria-managed binaries markdown section, if any."""
    if not aria_bin_dir:
        return []
    aria_bins = sorted(
        f.name
        for f in aria_bin_dir.iterdir()
        if f.is_file() and os.access(f, os.X_OK) and not f.name.startswith(".")
    )
    if not aria_bins:
        return []
    return [
        "### Aria-Managed Binaries\n",
        f"The binaries are installed in `{aria_bin_dir}` are "
        "automatically on $PATH. They will be available on PATH for all shell commands",
        "",
        f"Download and/or additional binaries to `{aria_bin_dir}`: download → `chmod +x` → verify. Shared across agents.",
        "",
    ]


def _render_extras(rows: list[tuple[str, list[str]]]) -> str:
    """Render the categorized extras as a markdown table string."""
    lines: list[str] = _aria_managed_section(_get_aria_bin_dir())
    lines.append("### Virtual Environment Commands\n")
    lines.append(
        "You can use these commands in your active virtual environment by calling them with `shell`. "
        "Use them when your registered tools aren't enough to get the job done.\n"
    )
    lines.append("| Category | Commands |")
    lines.append("|----------|----------|")
    for category, members in rows:
        lines.append(f"| {category} | `{'`, `'.join(members)}` |")
    lines.append("")
    lines.append(
        "Always run `<command> --help` before using any new command for the first time."
    )
    return "\n".join(lines)


def venv_extras_available() -> bool:
    """Return True if the active venv contains agent-usable CLI binaries."""
    bin_dir = _get_venv_bin_dir()
    if not bin_dir or not bin_dir.exists():
        return False
    return bool(
        _scan_venv_binaries(bin_dir, _EXCLUDED_BINARIES, _EXCLUDED_PATTERNS, None)
    )


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

    available = _scan_venv_binaries(
        bin_dir,
        _EXCLUDED_BINARIES | (excluded or set()),
        _EXCLUDED_PATTERNS,
        filter_term,
    )
    if not available:
        return "No extra CLI tools found in the virtual environment."
    return _render_extras(_categorize(available))


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

    available = _scan_venv_binaries(
        bin_dir,
        _EXCLUDED_BINARIES | (excluded or set()),
        _EXCLUDED_PATTERNS,
        filter_term,
    )
    categories: dict[str, list[str]] = {}
    uncategorized: list[str] = []
    for category, members in _categorize(available):
        if category == "Other":
            uncategorized = members
        else:
            categories[category] = members

    return {
        "categories": categories,
        "uncategorized": uncategorized,
        "total": len(available),
    }
