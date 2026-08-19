"""AX CLI — Agent Experience command-line interface.

A stripped-down CLI exposing only agent-facing commands:
web, knowledge, dev, worker, processes, and check.

Human management commands (users, server, config, system, models, vllm,
lightpanda) are only available through the full ``aria`` CLI.
"""


def main():
    import sys

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

    # Entry-point gate (Decision 3): the agent CLI needs models/tools ready,
    # so refuse every command until `aria init` has completed. Help-style
    # invocation (no subcommand, or a leading flag) still passes so users
    # can discover the CLI before setup.
    from aria.bootstrap import _allowed_before_init, is_init_completed

    if not is_init_completed():
        first = sys.argv[1] if len(sys.argv) > 1 else None
        if not _allowed_before_init(first):
            sys.stderr.write("Aria is not set up yet. Run: aria init\n")
            sys.exit(1)

    from aria.ax_cli.app import app

    app()


if __name__ == "__main__":
    main()
