# FROZEN (protocol) — see CONTRACTS.md
"""The `Clock` seam (sw-design.md §3).

Injected so timestamps are reproducible in tests and golden reports.
`SystemClock` and `FrozenClock` are A4's; **nothing calls `datetime.now()`
directly** outside this module.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FrozenClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware, UTC. Never naive — every stored timestamp carries
        its offset so a Windows and a Linux run agree."""
        ...


class SystemClock:
    """The production `Clock`. A4 owns any further behaviour."""

    def now(self) -> datetime:
        return datetime.now(UTC)


# --- STUB implementation — owned by A4 (feat/m2-infra). Not frozen. ---


class FrozenClock:
    """A `Clock` that does not move unless a test moves it.

    Reproducible timestamps for golden-file tests and E2E screenshots: two
    instances constructed with the same `now` return byte-identical values
    forever, on every call, from every thread.
    """

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now if now is not None else datetime(2026, 9, 2, 9, 30, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float) -> None:
        """Move the clock forward. A clock never rewinds."""
        if seconds < 0:
            raise ValueError("FrozenClock cannot move backward")
        self._now += timedelta(seconds=seconds)
