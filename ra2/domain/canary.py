# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""The cp1252 canary — one corpus-level check, nothing more (mvp-spec.md §4.4).

The delivered text has been through a lossy cp1252 -> Latin-1 conversion that
**deletes** characters rather than substituting them, so decoding cannot detect
it. The app does **not** attempt to measure it per record: the source system
runs no spell check, so dropped characters and ordinary typos are
indistinguishable.

One decisive check is kept: count characters from the Windows-1252-only set
across the whole corpus. **Zero, in a corpus containing French, proves the
conversion happened** (D11). Its only purpose is to justify asking for a UTF-8
re-export.

Read the negative carefully, because it is the whole design. A zero count is
evidence about the *pipeline*, not a score for any record, and it is only
evidence when French is present — German and Italian use almost none of these
characters, so zero in a German-only corpus says nothing. That condition is
enforced in `canary_finding`, not left to the caller.
"""

from collections.abc import Iterable
from typing import Final

from ra2.domain.findings import DEFAULT_SEVERITY, Finding, FindingCode
from ra2.domain.language import Language

__all__ = [
    "CP1252_ONLY_CHARS",
    "CanaryResult",
    "canary_finding",
    "count_canary_chars",
    "count_canary_chars_by_char",
]

#: The Windows-1252-only set from mvp-spec.md §4.4, verbatim.
CP1252_ONLY_CHARS: Final = frozenset("œŒ‘’“”–—…€™šžŠŽŸ‚„†‡‰‹›ˆ˜•")

#: The one language whose absence makes a zero count meaningless (§4.4).
CANARY_LANGUAGE: Final = Language.FR


class CanaryResult:
    """The corpus-level number, and whether it is evidence.

    A plain `int` would let a caller report "0 — conversion proven" for a
    German-only corpus, which is false. This carries the condition with the
    number.
    """

    __slots__ = ("count", "languages")

    def __init__(self, count: int, languages: frozenset[str]) -> None:
        self.count = count
        self.languages = languages

    @property
    def proves_lossy_conversion(self) -> bool:
        """Zero occurrences in a corpus that contains French (§4.4)."""
        return self.count == 0 and CANARY_LANGUAGE.value in self.languages


def count_canary_chars(texts: Iterable[str]) -> int:
    """Total occurrences of `CP1252_ONLY_CHARS` across a whole corpus.

    One number, stored on the corpus. No per-record markers, no per-language
    damage rate.
    """
    return sum(1 for text in texts for char in text if char in CP1252_ONLY_CHARS)


def count_canary_chars_by_char(texts: Iterable[str]) -> dict[str, int]:
    """The same count, broken down by character — for the import report only.

    Still corpus-level. It answers "which characters survived", which is what
    an upstream conversation about a re-export actually needs, without becoming
    a per-record or per-language measure.
    """
    counts: dict[str, int] = {}
    for text in texts:
        for char in text:
            if char in CP1252_ONLY_CHARS:
                counts[char] = counts.get(char, 0) + 1
    return counts


def canary_finding(
    count: int,
    languages: Iterable[str],
) -> Finding | None:
    """`CP1252_CANARY_ZERO` when, and only when, the count is evidence.

    Returns `None` for a non-zero count (nothing to report) and for a zero count
    in a corpus with no French (not evidence, §4.4).
    """
    present = frozenset(languages)
    result = CanaryResult(count=count, languages=present)
    if not result.proves_lossy_conversion:
        return None
    return Finding(
        code=FindingCode.CP1252_CANARY_ZERO,
        severity=DEFAULT_SEVERITY[FindingCode.CP1252_CANARY_ZERO],
        detail={
            "canary_count": str(count),
            "languages": ",".join(sorted(present)),
        },
    )
