## Failure Handling

### Transparency

- **Partial Results**: Deliver what works, even if incomplete. Flag gaps explicitly.
- **Graceful Degradation**: If a tool or service is partially working, prefer degraded results with a clear disclaimer over blocking entirely.

### Retry Policy

- **Transient Failures**: Retry *once* (e.g., timeouts, rate limits).
- **Deterministic Failures**: Do not retry (e.g., permission denied, missing files).

### Tool Parameter Verification

- If a tool call fails due to parameter formatting, **do not retry**. Report the error and adapt.
- If `ax` returns an `unknown_command` or `unknown_family` error, **read the `available_commands` or `available_families` list in the response** and use a valid one if one applies. If none applies, follow the Tool Priority Resolution Order: check `ax check extras` for a matching venv binary, then fall back to a common `shell` command. Never retry the identical invalid `ax` call.
