# FROZEN — see CONTRACTS.md
"""What services return: detached, immutable read models.

`ra2/ui/` must never touch a session or an ORM object (§12.7), and no ORM
object crosses the API boundary. Both adapters therefore get these — plain
frozen dataclasses, safe to render after the session has closed.

`ra2/api/schemas.py` mirrors these as Pydantic models. Two definitions, on
purpose: the wire format is allowed to differ from the internal shape without
dragging Pydantic into the service layer.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ra2.domain.census import CensusBucket, TypeHint, ValueCount
from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.findings import Finding
from ra2.domain.ids import CensusColumnId, CorpusId, DeliveryId, FileId

__all__ = [
    "CensusBucket",
    "CensusColumnView",
    "CensusSummary",
    "CorpusView",
    "DeliveryFileView",
    "DeliveryView",
    "Page",
    "SortDir",
]


class SortDir(StrEnum):
    """Sort direction. Always an explicit **service-call parameter**, even when
    the dataset is small enough to sort in memory (sw-design.md §8.4)."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a filtered, sorted query.

    `total` is the unpaged count matching the filter — the design's "1–25 of
    162" needs both numbers, and pagination disables rather than hides.
    """

    items: tuple[T, ...]
    total: int
    page: int
    page_size: int
    sort_key: str
    sort_dir: SortDir


@dataclass(frozen=True, slots=True)
class DeliveryFileView:
    """One row of the Import view's two file tables."""

    file_id: FileId
    filename: str
    relative_path: str
    byte_size: int
    sha256: str
    file_kind: FileKind
    set_key: str | None
    canton: str | None
    #: Effective settings, and what detection said before any override — the
    #: file report modal shows both (sw-design.md §8.3).
    encoding: str | None
    encoding_detected: str | None
    delimiter: str | None
    quote_char: str | None
    row_count: int | None
    ok_count: int
    recovered_count: int
    rejected_count: int
    header_ok: bool | None
    selected: bool
    analysed_at: datetime | None
    #: Every recovered and rejected row, with its key.
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True, slots=True)
class DeliveryView:
    """A delivery and its files. Feeds the whole Import view."""

    delivery_id: DeliveryId
    name: str
    source_kind: SourceKind
    root_path: str | None
    status: DeliveryStatus
    created_at: datetime
    analysed_at: datetime | None
    files: tuple[DeliveryFileView, ...] = ()

    @property
    def selected_record_count(self) -> int:
        """The "Create corpus · N records" label: the `unfall` rows of the
        selected files. Computed here, not in a view function (§8.1)."""
        return sum(
            f.ok_count for f in self.files if f.selected and f.file_kind is FileKind.UNFALL
        )


@dataclass(frozen=True, slots=True)
class CorpusView:
    """One row of the Corpora table."""

    corpus_id: CorpusId
    name: str
    version: int
    description: str | None
    imported_at: datetime
    record_count: int
    #: mvp-spec.md §9 — drives the "smoke test, not a result" marker.
    is_dev_sized: bool
    #: mvp-spec.md §4.4 — 0 renders in `--danger`, non-zero in `--warn`.
    cp1252_canary_count: int
    #: The design's "de 2 812 · fr 1 402 · it 396".
    language_counts: Mapping[str, int]
    delivery_id: DeliveryId | None
    #: > 0 renders the `LOCKED · N eval` pill and blocks delete (§6.3, J3).
    locked_by_evaluations: int = 0

    @property
    def is_locked(self) -> bool:
        return self.locked_by_evaluations > 0


@dataclass(frozen=True, slots=True)
class CensusColumnView:
    """One row of the Census table. Every number is stored, none recomputed."""

    census_column_id: CensusColumnId
    table_name: str
    column_name: str
    type_hint: TypeHint
    record_count: int
    populated_count: int
    populated_rate: float
    distinct_count: int
    top_value_share: float
    long_tail: bool
    #: Top 20 stored; top 4 rendered as bar segments, top 3 in the legend.
    top_values: tuple[ValueCount, ...] = ()
    #: Phase 1 has no feature config, so this is always `False` and the
    #: "use as feature" action renders disabled (plan-phase-1.md §1).
    in_config: bool = False


@dataclass(frozen=True, slots=True)
class CensusSummary:
    """The two summary cards, plus the `table · all 162` chip's counts."""

    corpus_id: CorpusId
    buckets: tuple[CensusBucket, ...]
    #: `{"unfall": 67, "objekt": 77, "person": 18}`.
    column_counts_by_table: Mapping[str, int]
    total_column_count: int
