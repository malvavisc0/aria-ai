"""AX CLI — Agent Experience command-line interface.

A stripped-down CLI exposing only agent-facing commands:
web, knowledge, dev, worker, processes, and check.

Human management commands (users, server, config, system, models, vllm,
lightpanda) are only available through the full ``aria`` CLI.
"""


def main():
    from aria.initializer import (
        is_initialized,
        run_initialization,
        setup_chainlit_config,
        setup_public_assets,
    )

    if not is_initialized():
        run_initialization()

    # Idempotent — mirrors the aria CLI entry point.
    setup_public_assets()
    setup_chainlit_config()

    from aria.ax_cli.app import app

    app()


if __name__ == "__main__":
    main()
