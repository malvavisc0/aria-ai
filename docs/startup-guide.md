# Aria Project Startup Guide

This document describes how to start the Aria project via CLI and GUI, including the initialization flow and server management.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Starting the Project](#starting-the-project)
  - [CLI Method](#cli-method)
  - [GUI Method](#gui-method)
- [First-Time Initialization](#first-time-initialization)
- [Server Management](#server-management)
- [Preflight Checks](#preflight-checks)
- [Architecture Overview](#architecture-overview)

## Prerequisites

- Python 3.12 or higher
- `uv` package manager (recommended) or pip
- Git (for cloning the repository)

### Optional Hardware

Aria supports multiple compute platforms:

| Platform | Description |
|----------|-------------|
| NVIDIA GPU | CUDA acceleration with VRAM for model inference (via vLLM) |
| CPU-only | Fallback mode without GPU acceleration (slower) |

The preflight checks automatically detect your platform and adjust memory requirements accordingly.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd aria

# Install dependencies with uv
uv sync   # CPU-only torch pinned automatically via [tool.uv] index

# Or install with GUI support
uv sync --extra gui
```

## Starting the Project

### CLI Method

The CLI provides full control over the Aria system, including server management, user administration, and model downloads.

#### Start the Web Server

```bash
# Run in foreground (blocking, Ctrl+C to stop)
aria server run

# Start in background
aria server start

# Check server status
aria server status

# Stop the server
aria server stop
```

#### Other CLI Commands

```bash
# Check system readiness (preflight runs automatically on server start)
ax check preflight

# User management
aria users list
aria users add

# Model management
aria models list
aria models download

# System information
aria system info
aria system gpu

# Configuration
aria config show

# Agent-facing commands — use the `ax` CLI (entry point: `ax`)
ax web search "query"            # Web search
ax web fetch "url"               # Fetch URL content (auto-detects file vs website)
ax web visit "url"               # Visit a page in the browser (stays open for click)
ax web click "selector"          # Click element on the current page
ax web close                     # Close browser page
ax web weather "city"            # Weather forecast
ax web youtube "url"             # YouTube transcript
ax memory store "key" "value"    # Persistent key-value memory across sessions
ax memory recall "key"
ax knowledge status              # Knowledge hub indexing state
ax knowledge reindex             # Re-scan documents directory
ax dev run "code"                # Execute Python
ax processes list                # Manage background processes
ax worker spawn --prompt "..."   # Background worker
ax check ...                     # Preflight checks

# aria management CLI (entry point: `aria`)
aria tools cleanup-sessions      # Tool state maintenance
aria storage sweep               # Reclaim orphaned element files
```

### GUI Method

The GUI provides a graphical interface for server management and monitoring.

```bash
# Launch the GUI application
aria-gui
```

The GUI window provides:
- **Overview tab**: Server status, PID, URL, uptime
- **Setup tab**: Download binaries and models
- **Users tab**: Manage user accounts
- **Logs tab**: View application logs

Use the Start/Stop/Open buttons to control the web server.

## First-Time Initialization

On first launch (both CLI and GUI), Aria automatically performs initialization:

```mermaid
flowchart TD
    A[Start aria or aria-gui] --> B{.env exists with CHAINLIT_AUTH_SECRET?}
    B -->|No| C[First-Time Setup]
    C --> D[Create .env from .env.example]
    C --> E[Create data/storage/chromadb directories]
    C --> F[Create SQLite database]
    C --> G[Create log file]
    D --> H[Generate CHAINLIT_AUTH_SECRET]
    B -->|Yes| I[Continue to CLI/GUI]
    H --> I
```

### What Gets Created

| Item | Location | Description |
|------|----------|-------------|
| `.env` | Project root | Configuration with generated auth secret |
| `data/` | Project root | Database and binaries |
| `storage/` | Project root | Uploaded files |
| `chromadb/` | Project root | Vector database |
| `aria.db` | `data/` | SQLite database |
| `logs/` | Project root | `debug.log` (app) + `tools.log` (tool calls) + `startup-error.txt` |

## Server Management

### Server Lifecycle

```mermaid
flowchart LR
    A[Start Command] --> B[Run Preflight Checks]
    B --> C{All Checks Pass?}
    C -->|No| D[Show Errors and Exit]
    C -->|Yes| E[Start Chainlit Process]
    E --> F[Wait for /health Endpoint]
    F --> G{Health Check OK?}
    G -->|Yes| H[Server Ready]
    G -->|No| I[Timeout Error]
```

### ServerManager

Both CLI and GUI use the [`ServerManager`](../src/aria/server/manager.py) class to control the Chainlit webserver:

| Method | Description |
|--------|-------------|
| `start()` | Start server in background |
| `run()` | Run server in foreground (blocking) |
| `stop()` | Stop the server |
| `is_running()` | Check if process is alive |
| `is_healthy()` | Check if `/health` returns 200 |
| `get_status()` | Get detailed status info |

### Process State

Server state is persisted to `data/server.json`:

```json
{
  "pid": 12345,
  "host": "localhost",
  "port": 9876,
  "started_at": "2026-02-26T10:00:00"
}
```

This allows the GUI to track servers started by the CLI and vice versa.

## Preflight Checks

Before starting the server, Aria validates the environment:

| Category | Checks |
|----------|--------|
| Environment | Required env vars (DATA_FOLDER, CHAINLIT_AUTH_SECRET, etc.) |
| Storage | Data folder exists, knowledge DB accessible |
| Binaries | vLLM installed, Lightpanda (optional) |
| Models | Chat model downloaded, embeddings model available |
| Hardware | GPU available, sufficient VRAM, memory requirements |
| Connectivity | vLLM server reachable |
| Tools | Core + file tools load correctly |

### Running Preflight Manually

```bash
# CLI
ax check preflight

# The server commands also run preflight automatically
aria server run
```

### Preflight Failures

If preflight fails, the server will not start. Common fixes:

```bash
# Install vLLM
aria vllm install

# Download missing models
aria models download

# Check environment
aria config show
```

## Architecture Overview

### Entry Points

Defined in [`pyproject.toml`](../pyproject.toml):

```toml
[project.scripts]
aria = "aria:main"              # Management CLI
ax = "aria.ax_cli:main"         # Agent-facing CLI
aria-gui = "aria.gui:main"      # GUI entry point
```

### Component Flow

```mermaid
flowchart TD
    subgraph Entry Points
        A[aria CLI]
        B[aria-gui GUI]
    end
    
    subgraph Initialization
        C[aria/__init__.py:main]
        D[aria/gui/__init__.py:main]
        E[initializer.py]
    end
    
    subgraph Server Control
        F[CLI: aria server run/start]
        G[GUI: Start Button]
        H[ServerManager]
    end
    
    subgraph Web Application
        I[chainlit run web_ui.py]
        J[on_app_startup]
        K[VLLMServerManager]
        L[Start vLLM inference server]
    end
    
    A --> C
    B --> D
    C --> E
    D --> E
    F --> H
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L
```

### Key Files

| File | Purpose |
|------|---------|
| [`src/aria/__init__.py`](../src/aria/__init__.py) | CLI entry point (`aria`) |
| [`src/aria/gui/__init__.py`](../src/aria/gui/__init__.py) | GUI entry point (`aria-gui`) |
| [`src/aria/ax_cli/app.py`](../src/aria/ax_cli/app.py) | Agent-facing `ax` CLI |
| [`src/aria/initializer.py`](../src/aria/initializer.py) | First-run setup |
| [`src/aria/preflight.py`](../src/aria/preflight.py) | Environment validation |
| [`src/aria/cli/main.py`](../src/aria/cli/main.py) | Management CLI commands |
| [`src/aria/cli/server.py`](../src/aria/cli/server.py) | Server CLI commands |
| [`src/aria/server/manager.py`](../src/aria/server/manager.py) | Server lifecycle |
| [`src/aria/web_ui.py`](../src/aria/web_ui.py) | Chainlit application (thin entry) |
| [`src/aria/web/lifecycle.py`](../src/aria/web/lifecycle.py) | Startup/shutdown handlers |
| [`src/aria/web/state.py`](../src/aria/web/state.py) | Global `AppState` singleton |
| [`src/aria/gui/windows/main_window.py`](../src/aria/gui/windows/main_window.py) | GUI main window |
| [`src/aria/gui/windows/server_handlers.py`](../src/aria/gui/windows/server_handlers.py) | GUI server controls |
| [`src/aria/agents/worker.py`](../src/aria/agents/worker.py) | Worker agent factory |

## Troubleshooting

### Server Won't Start

1. Run `ax check preflight` to identify issues
2. Check logs in `data/logs/debug.log`
3. Verify all models are downloaded: `aria models list`
4. Verify vLLM is installed: `aria vllm status`

### Port Already in Use

```bash
# Check what's using the port
lsof -i :9876

# Or change the port in .env
SERVER_PORT = 9877
```

### GUI Not Available

The GUI requires the `gui` extra:

```bash
uv sync --extra gui
```

### Database Issues

```bash
# Check database connectivity
ax check preflight

# The database file is located at
data/aria.db