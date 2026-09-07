# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""RFC4180 reading with an explicit `Dialect` (mvp-spec.md §4.2.2)."""

from collections.abc import Iterator
from dataclasses import dataclass

from ra2.domain.delivery import Dialect

__all__ = ["RawRow", "read_rows"]


@dataclass(frozen=True, slots=True)
class RawRow:
    """One physical row as read, before recovery or validation."""

    line_no: int
    fields: tuple[str, ...]
    #: Set when the reader itself could not parse the row.
    error: str | None = None


def read_rows(text: str, dialect: Dialect) -> Iterator[RawRow]:
    """Read `text` with a real RFC4180 parser using `dialect`."""
    raise NotImplementedError
