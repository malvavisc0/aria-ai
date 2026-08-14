# Release & Deployment

This document describes how Aria is released: the CI/CD pipeline, versioning strategy, and how to publish a new release.

---

## Overview

When a version tag (e.g. `v0.1.0`) is pushed to GitHub, a GitHub Actions workflow automatically:

1. **Validates** that the tag version matches `__version__` in `src/aria/__init__.py`
2. **Builds** standalone GUI applications for three platforms:
   - **Linux** — AppImage (`Aria-x86_64.AppImage`)
   - **Windows** — Portable .exe zip (`Aria-Windows-x86_64.zip`)
   - **macOS** — .app bundle zip (`Aria-macOS-arm64.zip`, Apple Silicon)
3. **Publishes** the Python package to [PyPI](https://pypi.org/project/aria-ai/) using trusted publishing (OIDC)
4. **Creates** a GitHub Release with all artifacts attached

---

## Versioning

The version is defined in a **single source of truth**:

```
src/aria/__init__.py
```

```python
__version__ = "0.1.0"
```

At build time, `setuptools` reads this value dynamically via:

```toml
# pyproject.toml
[project]
dynamic = ["version"]

[tool.setuptools.dynamic]
version = { attr = "aria.__version__" }
```

There is **no hardcoded version** in `pyproject.toml`. This eliminates the risk of version drift between files.

### Version Validation

The CI pipeline enforces that the git tag and the `__version__` string match before any build or publish job runs:

| Source | Example |
|--------|---------|
| Git tag | `v0.1.0` |
| Tag after stripping `v` prefix | `0.1.0` |
| `__version__` in `src/aria/__init__.py` | `0.1.0` |

If they don't match, the `validate-version` job fails immediately with a clear error message.

---

## How to Create a Release

### 1. Update the version

Edit `src/aria/__init__.py`:

```python
__version__ = "X.Y.Z"
```

### 2. Commit and tag

```bash
git add src/aria/__init__.py
git commit -m "bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### 3. CI takes over

The push of `vX.Y.Z` triggers `.github/workflows/release.yml`. You can monitor progress in the [Actions tab](https://github.com/malvavisc0/aria-ai/actions).

---

## Workflow Jobs

```
┌───────────────────┐
│ validate-version  │  ← fails fast if tag ≠ __version__
└────────┬──────────┘
         │
   ┌─────┴──────┬───────────┬──────────┬───────────┬──────────────┐
   ▼            ▼           ▼          ▼           ▼              ▼
┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐
│ Linux  │ │ Windows  │ │  macOS   │ │  PyPI    │ │build-whisper│ ← CUDA whisper-server tarball
│AppImage│ │  .exe    │ │  .app    │ │ publish  │ │  (static)   │
└───┬────┘ └────┬─────┘ └────┬─────┘ └─────┬────┘ └──────┬─────┘
    │           │             │             │             │
    └───────────┴─────────────┴──────┬──────┴─────────────┘
                                     │
                              ┌──────┴──────┐
                              │Docker (×4)  │  ← needs publish-pypi; GHCR: aria-cuda + aria-rocm + aria-lite + aria-arm64
                              └──────┬──────┘
                                     │
                              ┌──────┴──────┐
                              │   release   │  ← needs all jobs; GitHub Release with every artifact
                              └─────────────┘
```

### Job Details

| Job | Runner | Description |
|-----|--------|-------------|
| `validate-version` | ubuntu-latest | Compares tag version against `__version__` |
| `build-appimage` | ubuntu-22.04 | PyInstaller → AppImage (Linux x86_64) |
| `build-windows` | windows-latest | PyInstaller → zipped .exe (Windows x86_64) |
| `build-macos` | macos-latest | PyInstaller → zipped .app (macOS arm64) |
| `build-whisper-cuda` | ubuntu-latest | Static CUDA `whisper-server` build → `whisper-server-cuda-12.6-x86_64.tar.gz` (attached to the release, consumed by the Docker images) |
| `publish-pypi` | ubuntu-latest | `uv build` → `pypa/gh-action-pypi-publish` |
| `build-docker` | ubuntu-latest | Docker matrix (×4) → GHCR: CUDA/CPU + ROCm + Debian lite + ARM64 |
| `release` | ubuntu-latest | Creates GitHub Release, attaches all artifacts |

All build and publish jobs depend on `validate-version` succeeding.
`build-whisper-cuda` needs only `validate-version` (runs in parallel with the
platform builds). `build-docker` depends on `publish-pypi` (so the image gets
the freshly published package). The `release` job depends on all build and
publish jobs — including `build-whisper-cuda` (its tarball is a release asset)
and `build-docker`.

---

## PyPI Publishing

Aria uses **trusted publishing** (OIDC) — no API tokens or secrets are needed in the repository. The workflow authenticates to PyPI using GitHub's `id-token: write` permission.

### One-Time Setup on PyPI

Before the first release, configure trusted publishing on [pypi.org](https://pypi.org):

1. Go to the `aria-ai` project on PyPI (or create it)
2. Navigate to **Manage** → **Publishing**
3. Add a new publisher:
   - **Owner**: `malvavisc0`
   - **Repository**: `aria-ai`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`

After this one-time setup, every tagged release automatically publishes to PyPI.

### Installation

```bash
pip install aria-ai
pip install aria-ai[gui]   # with GUI (PySide6) support
```

---

## Standalone Application Builds

### Linux (AppImage)

- Built on `ubuntu-22.04` using PyInstaller + `appimagetool`
- Output: `Aria-x86_64.AppImage`
- Usage:
  ```bash
  chmod +x Aria-x86_64.AppImage
  ./Aria-x86_64.AppImage
  ```

### Windows

- Built on `windows-latest` using PyInstaller
- Output: `Aria-Windows-x86_64.zip` (contains `aria-gui.exe` + dependencies)
- Usage: Extract and run `aria-gui.exe`

### macOS (Apple Silicon)

- Built on `macos-latest` (arm64) using PyInstaller
- Output: `Aria-macOS-arm64.zip` (contains `Aria.app`)
- Usage:
  ```bash
  xattr -cr Aria.app
  open Aria.app
  ```
- The `xattr` command removes the quarantine flag that macOS applies to unsigned apps downloaded from the internet.

---

## Docker Images

Four Docker image variants are built and pushed to GitHub Container Registry (`ghcr.io`) on every release:

| Variant | Base Image | Tag |
|---------|-----------|-----|
| CUDA/CPU | `vllm/vllm-openai:latest` | `ghcr.io/malvavisc0/aria-ai-cuda:latest` |
| ROCm (AMD) | `vllm/vllm-openai-rocm:latest` | `ghcr.io/malvavisc0/aria-ai-rocm:latest` |
| Debian (lite) | `debian:trixie-slim` | `ghcr.io/malvavisc0/aria-ai-lite:latest` |
| ARM64 | Debian-based (no GPU) | `ghcr.io/malvavisc0/aria-ai-arm64:latest` |

The **CUDA/CPU** and **ROCm** images include vLLM for local model serving plus Aria's web UI (Chainlit). The **lite** and **ARM64** images are lightweight alternatives with no GPU/vLLM — designed for users connecting to a remote LLM endpoint or running CPU-only (the ARM64 image targets Raspberry Pi and similar boards). Each image is tagged with both `latest` and the version number (e.g. `0.1.0`).

### Usage

```bash
# CUDA / CPU (local vLLM)
docker run -p 9876:9876 -v ./data:/app/data ghcr.io/malvavisc0/aria-ai-cuda:latest

# ROCm (AMD GPUs)
docker run -p 9876:9876 -v ./data:/app/data ghcr.io/malvavisc0/aria-ai-rocm:latest

# Lightweight — no GPU (remote LLM or CPU-only)
docker run -p 9876:9876 -v ./data:/app/data ghcr.io/malvavisc0/aria-ai-lite:latest

# ARM64 (Raspberry Pi etc., remote LLM or CPU-only)
docker run -p 9876:9876 -v ./data:/app/data ghcr.io/malvavisc0/aria-ai-arm64:latest
```

| Flag | Purpose |
|------|---------|
| `-p 9876:9876` | Expose the Chainlit web UI |
| `-v ./data:/app/data` | Persist databases, models, and config across restarts |

The CUDA/CPU and ROCm images use the same `Dockerfile` with a `BASE_IMAGE` build argument to select the vLLM variant. The lite and ARM64 images use separate lightweight Dockerfiles (no vLLM). Authentication to GHCR uses OIDC (`packages: write` permission) — no secrets required.

### Building Locally

```bash
# CUDA / CPU
docker build --build-arg BASE_IMAGE=vllm/vllm-openai:latest -t aria .

# ROCm (AMD)
docker build --build-arg BASE_IMAGE=vllm/vllm-openai-rocm:latest -t aria-rocm .

# Lightweight (no GPU)
docker build -f Dockerfile.debian -t aria-lite .
```

---

## Manual Trigger

The workflow can also be triggered manually via the GitHub Actions UI with `workflow_dispatch`. This is useful for testing or re-running a failed release. You'll be prompted to enter the tag (defaults to `v0.1.0`).

> **Note:** Manual dispatch runs all build and publish jobs (PyPI, Docker, platform binaries), but the **GitHub Release creation is skipped** because it requires a real tag ref (`if: startsWith(github.ref, 'refs/tags/')`). To create a full release with attached artifacts, push a version tag instead.