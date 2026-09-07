# FROZEN (protocol) — see CONTRACTS.md
"""The `IdFactory` seam (sw-design.md §3).

Injected so ids are reproducible in golden reports and E2E. `Uuid7Factory`
(production, time-ordered) and `SeededFactory` (deterministic) are A4's.
**Nothing calls `uuid4()` at a call site.**
"""

from typing import Protocol, runtime_checkable

__all__ = ["IdFactory", "Uuid7Factory"]


@runtime_checkable
class IdFactory(Protocol):
    def new_id(self) -> str:
        """A fresh opaque id. Callers wrap it in the right `NewType` from
        `ra2.domain.ids`."""
        ...


class Uuid7Factory:
    """The production `IdFactory`: UUIDv7, so ids sort by creation time.

    A4 owns the implementation; this stub keeps `create_app()` buildable.
    """

    def new_id(self) -> str:
        import uuid_utils  # noqa: PLC0415 - A4 replaces this module

        return str(uuid_utils.uuid7())
