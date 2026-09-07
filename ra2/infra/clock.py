# FROZEN (protocol) — see CONTRACTS.md
"""The `Clock` seam (sw-design.md §3).

Injected so timestamps are reproducible in tests and golden reports.
`SystemClock` and `FrozenClock` are A4's; **nothing calls `datetime.now()`
directly** outside this module.
"""

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "SystemClock"]


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
