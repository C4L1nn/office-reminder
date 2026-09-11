"""When an official sync fails, try again soon instead of in six hours.

A machine that starts with Windows usually runs its first sync before the
network is up (2026-09-11: "getaddrinfo failed" 29 seconds after sign-in).
`OfficialUpdateService.sync_all` does not raise for that — each source reports
`status: FAILED` inside the result — so the regular six-hour cycle was the only
retry and the official calendar went unchecked all morning.

A retry cannot be swallowed by the "recently synced" rule: `should_sync` looks
only at `last_success_at`, which a failed attempt never writes.
"""

from __future__ import annotations

#: Delays between attempts while sources keep failing. The last one repeats
#: until a sync succeeds: a DNS failure costs the servers nothing, and half an
#: hour still catches a network that comes back mid-morning.
RETRY_DELAYS_MS = (2 * 60_000, 5 * 60_000, 15 * 60_000, 30 * 60_000)


def failed_sources(result: dict | None) -> list[str]:
    """Source codes that reported a failure in a `sync_all` result."""
    if not isinstance(result, dict):
        return []
    found: list[str] = []
    gib = result.get("gib") or {}
    if isinstance(gib, dict):
        for year, outcome in gib.items():
            if isinstance(outcome, dict) and outcome.get("status") == "FAILED":
                found.append(str(outcome.get("source_code") or f"GIB_{year}"))
    sgk = result.get("sgk") or {}
    if isinstance(sgk, dict) and sgk.get("status") == "FAILED":
        found.append(str(sgk.get("source_code") or "SGK_NOTICES"))
    return found


def retry_delay_ms(attempt: int) -> int:
    """Delay before retry number `attempt` (0-based); the last step repeats."""
    return RETRY_DELAYS_MS[min(max(attempt, 0), len(RETRY_DELAYS_MS) - 1)]


__all__ = ["RETRY_DELAYS_MS", "failed_sources", "retry_delay_ms"]
