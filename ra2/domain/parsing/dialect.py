# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Delimiter and quote-character detection (mvp-spec.md §4.1)."""

from ra2.domain.delivery import Dialect, FileKind

__all__ = ["detect_dialect"]


def detect_dialect(text: str, kind: FileKind) -> Dialect:
    """Sniff the dialect of already-decoded text.

    `|` for the structured tables, `;` RFC4180 for the text file — but sniffed,
    not assumed, and overridable per file.
    """
    raise NotImplementedError
