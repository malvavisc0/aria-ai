#!/bin/sh
# docker-entrypoint.sh — Aria container entrypoint.
#
# Runs `aria init --non-interactive` once on every boot so a fresh
# /app/data volume is bootstrapped (env file, dirs, binaries, models),
# then execs into `aria server run`. Init is idempotent: a populated
# volume makes every step a no-op (env file exists, binaries present,
# model dirs present), so restarts stay fast.
#
# The read-only `./.env:/app/.env:ro` mount is handled by init's
# non-interactive read-only branch — env vars in the process environment
# are adopted as-is and the config.toml sync still runs (it writes
# inside the writable /app/data volume).
set -e

aria init --non-interactive
exec aria server run "$@"
