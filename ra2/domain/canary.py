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
"""

from collections.abc import Iterable
from typing import Final

__all__ = ["CP1252_ONLY_CHARS", "count_canary_chars"]

#: The Windows-1252-only set from mvp-spec.md §4.4, verbatim.
CP1252_ONLY_CHARS: Final = frozenset("œŒ‘’“”–—…€™šžŠŽŸ‚„†‡‰‹›ˆ˜•")


def count_canary_chars(texts: Iterable[str]) -> int:
    """Total occurrences of `CP1252_ONLY_CHARS` across a whole corpus.

    One number, stored on the corpus. No per-record markers, no per-language
    damage rate.
    """
    raise NotImplementedError
