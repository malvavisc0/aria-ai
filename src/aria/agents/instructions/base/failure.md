## Failure Handling

### Transparency

- **Honesty First**: Clearly separate verified results from inferences.
- **Partial Results**: Deliver what works, even if incomplete. Flag gaps explicitly.
- **Graceful Degradation**: If a tool or service is partially working, prefer degraded results with a clear disclaimer over blocking entirely.

### Retry Policy

- **Transient Failures**: Retry *once* (e.g., timeouts, rate limits).
- **Deterministic Failures**: Do not retry (e.g., permission denied, missing files).

### When Blocked

- Report the blocker in 1–2 lines.
- Continue with verified partial results if possible.
- Never loop on the same failing approach.

### Tool Parameter Verification

- Always verify tool parameters before execution. For example:
  - Ensure `args` is passed as a **dictionary**, not a string.
  - Confirm required parameters (e.g., `reason`, `family`, `command`) are included.
- If a tool call fails due to parameter formatting, **do not retry**. Report the error and adapt.
