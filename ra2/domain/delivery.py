# FROZEN — see CONTRACTS.md
"""Delivery vocabulary: what a file is, how it is read, and what came out.

A *delivery* is N cantonal sets of three structured files plus **one** text file
covering all cantons (mvp-spec.md §4.1). Nothing here is ever derived from a
filename: `FileKind` comes from the header (SD5), the canton comes from
`unfall.KantonAusw`, and the set grouping comes from FK reachability (SD6).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from ra2.domain.findings import Finding
from ra2.domain.ids import FileId

__all__ = [
    "STRUCTURED_KINDS",
    "UNFALL_UID_PATTERN",
    "DeliveryAnalysis",
    "DeliveryStatus",
    "Dialect",
    "Encoding",
    "FileAnalysis",
    "FileKind",
    "RowOutcome",
    "SourceKind",
]

#: A `UnfallUid` is exactly 32 hex characters. This is what key-anchored
#: recovery anchors on: a line not starting with this followed by the delimiter
#: is a continuation of the preceding record (mvp-spec.md §4.2.3).
UNFALL_UID_PATTERN: Final = r"^[0-9A-Fa-f]{32}"


class FileKind(StrEnum):
    """Which table a file holds — decided by header match only (SD5)."""

    UNFALL = "unfall"
    OBJEKT = "objekt"
    PERSON = "person"
    TEXT = "text"
    UNKNOWN = "unknown"


#: The three files that make up one cantonal set. The text file is shared by
#: the whole delivery and is deliberately not one of them (mvp-spec.md §4.1).
STRUCTURED_KINDS: Final = (FileKind.UNFALL, FileKind.OBJEKT, FileKind.PERSON)


class Encoding(StrEnum):
    """The only two encodings the pipeline tries, in this order.

    Undecodable bytes **fail the file**. There is no third fallback and
    `errors="replace"` is banned (mvp-spec.md §4.2.1, sw-design.md §12.4).
    """

    UTF_8 = "utf-8"
    CP1252 = "cp1252"


class SourceKind(StrEnum):
    """How a delivery's files got here (sw-design.md §6.1).

    Nothing downstream of the `FileStore` seam knows which was used.
    """

    UPLOAD = "upload"
    HOST_PATH = "host_path"


class DeliveryStatus(StrEnum):
    """Lifecycle of the staging area (sw-design.md §4.1)."""

    REGISTERED = "registered"
    ANALYSING = "analysing"
    ANALYSED = "analysed"
    FAILED = "failed"


class RowOutcome(StrEnum):
    """What happened to one physical row.

    `RECOVERED` is only ever reached by the two-column text file. A wide
    structured row with a stray delimiter is detected and `REJECTED`; repair is
    not attempted (mvp-spec.md §4.2.3).
    """

    OK = "ok"
    RECOVERED = "recovered"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Dialect:
    """The CSV dialect of one file.

    Per-file, defaulted by detection and **overridable** in the import UI
    (mvp-spec.md §4.1). Encoding is tracked separately because it is detected
    from bytes, before there is any text to sniff a delimiter from.
    """

    #: `|` for the structured files, `;` for the text file.
    delimiter: str
    #: `"` throughout the delivery seen so far; still per-file and overridable.
    quote_char: str = '"'


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    """The result of analysing one file (sw-design.md §6.2).

    Analyse is re-runnable: an encoding or delimiter override re-runs it for
    that file alone and replaces this whole value.
    """

    file_id: FileId
    filename: str
    kind: FileKind
    #: What detection said, before any analyst override.
    encoding_detected: Encoding | None
    dialect_detected: Dialect | None
    #: What was actually used — detection, unless overridden.
    encoding: Encoding | None
    dialect: Dialect | None
    #: The header as read, whitespace-trimmed, original case preserved.
    header: tuple[str, ...] = ()
    #: True when `header` matches `kind`'s canonical column set exactly.
    header_ok: bool = False
    row_count: int = 0
    ok_count: int = 0
    recovered_count: int = 0
    rejected_count: int = 0
    #: From `unfall.KantonAusw`, never from the filename (mvp-spec.md §4.1).
    canton: str | None = None
    #: Groups the three structured files of one canton (SD6).
    set_key: str | None = None
    findings: tuple[Finding, ...] = ()

    @property
    def has_blocking(self) -> bool:
        return any(f.is_blocking for f in self.findings)


@dataclass(frozen=True, slots=True)
class DeliveryAnalysis:
    """Per-file analyses plus the cross-file findings over the whole delivery.

    Uniqueness is verified across the **whole delivery**, not per file, because
    the single shared text file is the join target for every cantonal set
    (mvp-spec.md §4.1).
    """

    files: tuple[FileAnalysis, ...] = ()
    #: Cross-file findings: duplicate keys, orphan FKs, count mismatches,
    #: unmatched text keys. Per-file findings stay on `FileAnalysis`.
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def all_findings(self) -> tuple[Finding, ...]:
        return tuple(f for a in self.files for f in a.findings) + self.findings

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.all_findings if f.is_blocking)
