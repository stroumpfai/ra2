# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Key-anchored recovery (mvp-spec.md §4.2.3).

A line that does not begin with `^[0-9A-Fa-f]{32}<delim>` is a **continuation
of the preceding record**, not a new row.

- Two-column text file: repairs embedded newlines unambiguously -> `RECOVERED`.
- Wide structured tables: **detects** a stray delimiter; repair is not
  attempted. The row is `REJECTED` and reported with its key.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ra2.domain.delivery import Dialect, FileKind, RowOutcome
from ra2.domain.findings import Finding
from ra2.domain.parsing.reader import RawRow

__all__ = ["RecoveredRow", "recover_rows"]


@dataclass(frozen=True, slots=True)
class RecoveredRow:
    """One logical row plus what had to happen to get it."""

    line_no: int
    fields: tuple[str, ...]
    outcome: RowOutcome
    key: str | None
    findings: tuple[Finding, ...] = ()


def recover_rows(
    rows: Iterable[RawRow],
    *,
    kind: FileKind,
    dialect: Dialect,
    expected_field_count: int,
) -> Iterator[RecoveredRow]:
    """Reassemble continuations, reject what cannot be repaired.

    Every recovered and every rejected row carries a `Finding` with its key.
    Nothing is silently repaired and nothing is silently dropped.
    """
    raise NotImplementedError
