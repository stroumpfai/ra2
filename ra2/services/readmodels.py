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
from ra2.domain.codelist_coverage import ColumnCoverage
from ra2.domain.codes import CodeValue
from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.feature import DerivationSpec, Grain, Kind, MatchingRule, ValueType
from ra2.domain.findings import Finding
from ra2.domain.ids import (
    CensusColumnId,
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    DeliveryId,
    FeatureConfigId,
    FeatureId,
    FileId,
)

__all__ = [
    "CensusBucket",
    "CensusColumnView",
    "CensusSummary",
    "CodeAttributeView",
    "CodelistImportResult",
    "ColumnMappingView",
    "CorpusSummary",
    "CorpusView",
    "DeliveryFileView",
    "DeliveryView",
    "FeatureConfigView",
    "FeatureSetSummary",
    "FeatureView",
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
        return sum(f.ok_count for f in self.files if f.selected and f.file_kind is FileKind.UNFALL)


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
class CorpusSummary:
    """The Corpora card's header count: "4 imported · 2 locked by an
    evaluation" (design README §1b). Over the whole table, not over a page —
    a property of the corpus set, not of what is on screen."""

    total: int
    locked: int


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
    #: Phase 1 has no feature config, so this was always `False` (the "use as
    #: feature" action rendered disabled, plan-phase-1.md §1). Phase 2 (M9)
    #: turns this real: `True` once some feature's `source_column` names this
    #: column (plan-phase-2.md §2, "deliberately deferred inside phase 2") —
    #: computed from `feature.source_column`, never stored, since a feature
    #: carries no FK back to a census column.
    in_config: bool = False


@dataclass(frozen=True, slots=True)
class CensusSummary:
    """The two summary cards, plus the `table · all 162` chip's counts."""

    corpus_id: CorpusId
    buckets: tuple[CensusBucket, ...]
    #: `{"unfall": 67, "objekt": 77, "person": 18}`.
    column_counts_by_table: Mapping[str, int]
    total_column_count: int


# ===========================================================================
# Codelists (F3) — phase 2, mvp-spec.md §7, sw-design.md §14.
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CodeAttributeView:
    """One imported attribute — the Codelists edit zone's JSON-key dropdown
    options, and its "mapped to X · N keys, M mapped" header line."""

    code_attribute_id: CodeAttributeId
    key: str
    chapter: str | None
    name: Mapping[str, str]
    code_count: int


@dataclass(frozen=True, slots=True)
class ColumnMappingView:
    """One row of the Codelists master list: one census `enum` column, its
    mapping if any, and its coverage status (sw-design.md §14.2)."""

    corpus_id: CorpusId
    table_name: str
    column_name: str
    distinct_in_corpus: int
    mapping_id: ColumnMappingId | None
    mapped_attribute: CodeAttributeView | None
    #: `None` exactly when `mapped_attribute` is `None`.
    coverage: ColumnCoverage | None
    #: Feature names reading this column (C5, plan-phase-2.md §2) — inert
    #: (always empty) until a feature actually exists to populate it.
    used_by_features: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodelistImportResult:
    """What one "Import Codes as JSON" action returns.

    `no_change=True` is not an error (F1, plan-phase-2.md §9): a re-upload of
    the current file is reported "already current", not a new generation.
    """

    code_table_import_id: CodeTableImportId
    source_hash: str
    imported_at: datetime
    attribute_count: int
    no_change: bool = False


# ===========================================================================
# Features (F4) — phase 2, mvp-spec.md §8.
# ===========================================================================


@dataclass(frozen=True, slots=True)
class FeatureView:
    """One row of the Features flat list, and the edit zone's content for it."""

    feature_id: FeatureId
    feature_config_id: FeatureConfigId
    ordinal: int
    key: str
    kind: Kind
    description: str
    grain: Grain
    source_column: str | None
    derivation: DerivationSpec | None
    value_type: ValueType
    matching_rule: MatchingRule
    #: The snapshot taken at evaluation creation (§8.5) — always `None` in
    #: phase 2, since no evaluation exists yet to take one.
    enum_codelist: tuple[CodeValue, ...] | None
    #: The real value, set only once the enclosing set is frozen.
    fingerprint: str | None
    #: Q3 — always computable from the draft's current fields, shown with a
    #: "· preview" qualifier until frozen.
    fingerprint_preview: str
    #: Blocking validation messages (mvp-spec.md §7/§8.2). Non-empty rows
    #: render as errors and block "Create a feature set".
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeatureConfigView:
    """One feature set with its features — the Features toolbar/edit surface."""

    feature_config_id: FeatureConfigId
    name: str
    version: int
    description: str | None
    created_at: datetime
    frozen_at: datetime | None
    locked_by_evaluations: int = 0
    features: tuple[FeatureView, ...] = ()

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None


@dataclass(frozen=True, slots=True)
class FeatureSetSummary:
    """One row of the feature-sets strip below the Features split."""

    feature_config_id: FeatureConfigId
    name: str
    version: int
    description: str | None
    created_at: datetime
    feature_count: int
    frozen_at: datetime | None
    #: > 0 renders the `LOCKED · N eval` pill and disables rename/delete.
    locked_by_evaluations: int = 0

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None
