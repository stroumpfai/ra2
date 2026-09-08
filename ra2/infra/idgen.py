# FROZEN (protocol) — see CONTRACTS.md
"""The `IdFactory` seam (sw-design.md §3).

Injected so ids are reproducible in golden reports and E2E. `Uuid7Factory`
(production, time-ordered) and `SeededFactory` (deterministic) are A4's.
**Nothing calls `uuid4()` at a call site.**
"""

import random
import uuid
from typing import Protocol, runtime_checkable

import uuid_utils

__all__ = ["IdFactory", "SeededFactory", "Uuid7Factory"]


@runtime_checkable
class IdFactory(Protocol):
    def new_id(self) -> str:
        """A fresh opaque id. Callers wrap it in the right `NewType` from
        `ra2.domain.ids`."""
        ...


class Uuid7Factory:
    """The production `IdFactory`: UUIDv7, so ids sort by creation time."""

    def new_id(self) -> str:
        return str(uuid_utils.uuid7())


# --- STUB implementation — owned by A4 (feat/m2-infra). Not frozen. ---


class SeededFactory:
    """Deterministic, UUID-shaped ids: same seed, byte-identical sequence.

    Stands in for `Uuid7Factory` in golden-file tests and E2E, where the
    report format expects UUID-shaped strings but two runs must produce the
    exact same ones. `random.Random(seed)` is reseeded nowhere else in the
    app — this is the one place a fixed seed buys reproducibility rather than
    hiding a bug.
    """

    def __init__(self, seed: int = 0) -> None:
        self._random = random.Random(seed)

    def new_id(self) -> str:
        return str(uuid.UUID(int=self._random.getrandbits(128), version=4))
