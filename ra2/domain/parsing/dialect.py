# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Delimiter and quote-character detection (mvp-spec.md §4.1).

`|` for the structured tables, `;` RFC4180 for the text file — but **sniffed,
not assumed**, and overridable per file. The delivery's own documentation is
not a contract we can rely on: the point of detecting is that the next delivery
may differ, and that the analyst can see and correct what was detected.

The sniff is deliberately dull. It scores each candidate by how *stable* its
field count is over the first few lines, not by raw frequency: a `;` inside one
narrative beats `|` on frequency in a one-row file, but not on stability across
rows.
"""

import csv
from collections.abc import Sequence
from typing import Final

from ra2.domain.delivery import Dialect, FileKind

__all__ = ["CANONICAL_DELIMITERS", "CANDIDATE_DELIMITERS", "DEFAULT_QUOTE_CHAR", "detect_dialect"]

#: Tried in this order; ties fall to the earlier one, then to `kind`.
CANDIDATE_DELIMITERS: Final[tuple[str, ...]] = ("|", ";", ",", "\t")

#: What each kind is *expected* to use. Only ever a tie-breaker — never a
#: substitute for looking (mvp-spec.md §4.1).
CANONICAL_DELIMITERS: Final[dict[FileKind, str]] = {
    FileKind.UNFALL: "|",
    FileKind.OBJEKT: "|",
    FileKind.PERSON: "|",
    FileKind.TEXT: ";",
}

#: `"` throughout the delivery seen so far, doubled to escape (RFC4180).
DEFAULT_QUOTE_CHAR: Final = '"'

#: How many physical lines the sniff looks at. Enough to see a stable field
#: count, few enough that a 200k-row file costs nothing to classify.
_SNIFF_LINES: Final = 10


def _lines(text: str, limit: int) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            out.append(raw)
        if len(out) >= limit:
            break
    return out


def _score(lines: Sequence[str], delimiter: str, quote_char: str) -> tuple[int, int]:
    """`(lines agreeing with the header's field count, that field count)`.

    Zero when the delimiter never appears, so it can never win by default.
    """
    reader = csv.reader(lines, delimiter=delimiter, quotechar=quote_char)
    counts = [len(row) for row in reader]
    if not counts or counts[0] < 2:
        return (0, 0)
    return (sum(1 for c in counts if c == counts[0]), counts[0])


def detect_dialect(text: str, kind: FileKind) -> Dialect:
    """Sniff the dialect of already-decoded text.

    `|` for the structured tables, `;` RFC4180 for the text file — but sniffed,
    not assumed, and overridable per file.

    `kind` is a hint only, used to break a tie. It is normally `UNKNOWN` at this
    point in the pipeline: the header decides the kind (SD5) and the header
    cannot be read until the delimiter is known.
    """
    quote_char = DEFAULT_QUOTE_CHAR
    lines = _lines(text, _SNIFF_LINES)
    preferred = CANONICAL_DELIMITERS.get(kind)

    best_delimiter: str | None = None
    best_score = (0, 0)
    for candidate in CANDIDATE_DELIMITERS:
        score = _score(lines, candidate, quote_char)
        if score == (0, 0):
            continue
        if score > best_score or (score == best_score and candidate == preferred):
            best_delimiter, best_score = candidate, score

    if best_delimiter is None:
        # Nothing looked like a delimited file — a one-column file, or an empty
        # one. Fall back on what `kind` expects, and on `|` when even that is
        # unknown, so the caller still gets a usable Dialect to report.
        best_delimiter = preferred or CANDIDATE_DELIMITERS[0]

    return Dialect(delimiter=best_delimiter, quote_char=quote_char)
