# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""The canonical column sets, and the header match that decides `FileKind`.

**The header is the only thing that decides what a file is** (SD5,
sw-design.md §12.5). Matching is case-insensitive and whitespace-trimmed
(mvp-spec.md §4.1).

A1 fills the three canonical sets (67 `unfall` / 77 `objekt` / 18 `person`
columns) and the two-column text header, taking the **names only** from the
sample headers — never a data row, never a committed fixture built from real
values.
"""

from collections.abc import Sequence
from typing import Final

from ra2.domain.delivery import FileKind

__all__ = [
    "CANONICAL_HEADERS",
    "TEXT_KEY_COLUMN",
    "UNFALL_KEY_COLUMN",
    "match_header",
    "normalise_header",
]

#: `UnfallUid` in the structured files; the text file's header is upper-case.
UNFALL_KEY_COLUMN: Final = "UnfallUid"
TEXT_KEY_COLUMN: Final = "UNFALLUID"

#: Filled by A1 from the sample headers. Empty tuples here mean "not yet
#: known", not "no columns" — `match_header` must not report a match against an
#: empty set.
CANONICAL_HEADERS: Final[dict[FileKind, tuple[str, ...]]] = {
    FileKind.UNFALL: (),
    FileKind.OBJEKT: (),
    FileKind.PERSON: (),
    FileKind.TEXT: (),
}


def normalise_header(header: Sequence[str]) -> tuple[str, ...]:
    """Whitespace-trim and case-fold for comparison. Original case is kept
    on `FileAnalysis.header`; this is only the comparison key."""
    raise NotImplementedError


def match_header(header: Sequence[str]) -> FileKind:
    """Decide the file's kind from its header alone. No filename is consulted."""
    raise NotImplementedError
