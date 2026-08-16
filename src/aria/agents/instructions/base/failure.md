## Failure Handling

- **Read the error, then adapt** — never loop on the same failing approach.
- **Partial results:** deliver what works, even if incomplete; flag gaps explicitly. Prefer a degraded result with a clear disclaimer over blocking entirely.
- **Retry transient failures once** (timeouts, network hiccups, rate limits); never retry deterministic failures (permission denied, missing files, policy blocks).
- **On a parameter or `unknown_command`/`unknown_family` error:** never retry the identical call — use the `available_commands`/`available_families` in the response, or adapt.
