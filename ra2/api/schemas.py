# FROZEN — see CONTRACTS.md
"""Every request and response model for the four routers.

**No ORM object ever crosses this boundary** (plan-phase-1.md M4). These mirror
`ra2.services.readmodels`; the duplication is deliberate — the wire format is
allowed to move without dragging Pydantic into the service layer.

Field names are `snake_case` and match the read models one-for-one, so C1/C2
write mapping functions, not translations.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ra2.domain.census import CensusBucketLabel, TypeHint
from ra2.domain.delivery import DeliveryStatus, Encoding, FileKind, SourceKind
from ra2.domain.findings import FindingCode, Severity
from ra2.infra.tasks import TaskStatus
from ra2.services.readmodels import SortDir

__all__ = [
    "AnalyseResponse",
    "BlockingFindingsResponse",
    "CensusColumnResponse",
    "CensusPage",
    "CensusSummaryResponse",
    "CloneFeatureConfigRequest",
    "CodeAttributeResponse",
    "CodeImportErrorResponse",
    "CodeUsageResponse",
    "CodelistImportErrorResponse",
    "CodelistImportResponse",
    "ColumnCoverageResponse",
    "ColumnMappingResponse",
    "CorpusPage",
    "CorpusResponse",
    "CreateCorpusRequest",
    "CreateFeatureConfigRequest",
    "DeliveryFileResponse",
    "DeliveryResponse",
    "DerivationFilterSchema",
    "DerivationSpecSchema",
    "ErrorResponse",
    "FeatureConfigResponse",
    "FeatureConfigSummaryResponse",
    "FeatureRequest",
    "FeatureResponse",
    "FeatureValidationErrorResponse",
    "FileOverrideRequest",
    "FindingResponse",
    "MapColumnRequest",
    "MatchingRuleSchema",
    "PageMeta",
    "ProfileBucketResponse",
    "RegisterDeliveryRequest",
    "SelectFileRequest",
    "TaskProgressResponse",
    "ValueCountResponse",
]


class _Schema(BaseModel):
    """Strict by default: an unknown field in a request is a 422, not a
    silently ignored typo."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ===========================================================================
# Shared
# ===========================================================================


class FindingResponse(_Schema):
    """One reported outcome (sw-design.md §5).

    `detail` is structured data. The UI renders it from one table; the API
    never sends a pre-formatted sentence, so wording changes break no test.
    """

    code: FindingCode
    severity: Severity
    file_id: str | None = None
    #: `UnfallUid` / `ObjektUid` / `PersonUid` where known.
    key: str | None = None
    line_no: int | None = None
    detail: dict[str, str] = Field(default_factory=dict)


class ErrorResponse(_Schema):
    """The body of every 4xx that is not a validation error."""

    detail: str


class BlockingFindingsResponse(_Schema):
    """422 from a refused freeze. **Nothing was created** (J2)."""

    detail: str = "blocking validation findings; no corpus was created"
    findings: list[FindingResponse]


class PageMeta(_Schema):
    """Paging envelope. `total` is the unpaged count matching the filter."""

    total: int
    page: int
    page_size: int
    sort_key: str
    sort_dir: SortDir


# ===========================================================================
# /api/v1/deliveries  (C1)
# ===========================================================================


class RegisterDeliveryRequest(_Schema):
    name: str = Field(min_length=1, max_length=200)
    source_kind: SourceKind
    #: Required for `host_path`, forbidden for `upload`. Validated in the
    #: service, so the UI and the API reject it identically.
    root_path: str | None = None


class FileOverrideRequest(_Schema):
    """The file report modal's encoding/delimiter override (§8.3).

    `None` means "keep what is effective now". Applying it re-parses that file
    alone.
    """

    encoding: Encoding | None = None
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    quote_char: str | None = Field(default=None, min_length=1, max_length=1)


class SelectFileRequest(_Schema):
    selected: bool


class DeliveryFileResponse(_Schema):
    file_id: str
    filename: str
    relative_path: str
    byte_size: int
    sha256: str
    #: From the header, never the filename (SD5).
    file_kind: FileKind
    set_key: str | None = None
    #: From `unfall.KantonAusw`, never the filename.
    canton: str | None = None
    encoding: str | None = None
    encoding_detected: str | None = None
    delimiter: str | None = None
    quote_char: str | None = None
    row_count: int | None = None
    ok_count: int = 0
    recovered_count: int = 0
    rejected_count: int = 0
    header_ok: bool | None = None
    selected: bool = True
    analysed_at: datetime | None = None
    findings: list[FindingResponse] = Field(default_factory=list)


class DeliveryResponse(_Schema):
    delivery_id: str
    name: str
    source_kind: SourceKind
    root_path: str | None = None
    status: DeliveryStatus
    created_at: datetime
    analysed_at: datetime | None = None
    files: list[DeliveryFileResponse] = Field(default_factory=list)
    #: The "Create corpus · N records" label — computed by the service, so the
    #: UI and any script agree on the number (§8.1).
    selected_record_count: int = 0


class AnalyseResponse(_Schema):
    """Analyse is asynchronous; poll `GET /api/v1/tasks/{task_id}`."""

    task_id: str


# ===========================================================================
# /api/v1/corpora  (C1)
# ===========================================================================


class CreateCorpusRequest(_Schema):
    """Freeze the **selected** files of a delivery into one immutable corpus."""

    delivery_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class CorpusResponse(_Schema):
    corpus_id: str
    name: str
    version: int
    description: str | None = None
    imported_at: datetime
    record_count: int
    #: Drives the "smoke test, not a result" marker wherever it appears.
    is_dev_sized: bool = False
    #: 0 in a corpus containing French proves the lossy conversion happened.
    cp1252_canary_count: int = 0
    #: `{"de": 2812, "fr": 1402, "it": 396}`.
    language_counts: dict[str, int] = Field(default_factory=dict)
    delivery_id: str | None = None
    #: > 0 renders `LOCKED · N eval`; DELETE then returns 409.
    locked_by_evaluations: int = 0


class CorpusPage(_Schema):
    items: list[CorpusResponse]
    meta: PageMeta


# ===========================================================================
# /api/v1/census  (C2)
# ===========================================================================


class ValueCountResponse(_Schema):
    value_raw: str
    count: int
    #: `count / populated_count`, in [0, 1].
    share: float


class CensusColumnResponse(_Schema):
    census_column_id: str
    table_name: str
    column_name: str
    type_hint: TypeHint
    record_count: int
    #: Populated = non-empty string. Empty means *no value provided*.
    populated_count: int
    populated_rate: float
    distinct_count: int
    top_value_share: float
    #: SD8: `distinct_count > 20 and top_value_share < 0.01`.
    long_tail: bool
    #: Top 20 stored; the view renders 4 segments and 3 legend entries.
    top_values: list[ValueCountResponse] = Field(default_factory=list)
    #: Always `false` in phase 1 — no feature config exists yet.
    in_config: bool = False


class CensusPage(_Schema):
    items: list[CensusColumnResponse]
    meta: PageMeta


class ProfileBucketResponse(_Schema):
    label: CensusBucketLabel
    column_count: int


class CensusSummaryResponse(_Schema):
    """The two summary cards plus the table chip's counts."""

    corpus_id: str
    buckets: list[ProfileBucketResponse]
    column_counts_by_table: dict[str, int] = Field(default_factory=dict)
    total_column_count: int = 0


# ===========================================================================
# /api/v1/tasks  (C2)
# ===========================================================================


class TaskProgressResponse(_Schema):
    """What the UI polls with `ui.timer` (sw-design.md §9)."""

    task_id: str
    name: str
    status: TaskStatus
    done: int = 0
    total: int = 0
    message: str = ""
    #: Set only when `status` is `failed`. A failure is a recorded outcome.
    error: str | None = None


# ===========================================================================
# /api/v1/codelists  (F1)
# ===========================================================================


class CodeImportErrorResponse(_Schema):
    """One structural problem with an uploaded codelist file."""

    attribute_key: str | None = None
    path: str
    message: str


class CodelistImportErrorResponse(_Schema):
    """422 from a malformed upload. **Nothing was imported** (sw-design.md §14.1)."""

    detail: str = "malformed codelist upload; nothing was imported"
    #: Named to match `CodelistImportError.import_errors` (§12.4's banned
    #: `errors=` keyword; Wave 2's amendment,
    #: contracts/amendments/feat-p2-feature-service.md).
    import_errors: list[CodeImportErrorResponse]


class CodelistImportResponse(_Schema):
    code_table_import_id: str
    source_hash: str
    imported_at: datetime
    attribute_count: int
    #: A re-upload of the current file is "already current", not an error.
    no_change: bool = False


class CodeAttributeResponse(_Schema):
    """One imported attribute — the JSON-key mapping dropdown's options."""

    code_attribute_id: str
    key: str
    chapter: str | None = None
    name: dict[str, str] = Field(default_factory=dict)
    code_count: int


class CodeUsageResponse(_Schema):
    code: str
    count: int
    #: `count / populated_count`, in [0, 1].
    share: float
    label: str | None = None
    #: `false` is the danger row: the code has no row at all in the mapped
    #: attribute (sw-design.md §14.2) — distinct from merely unlabelled.
    in_codelist: bool


class ColumnCoverageResponse(_Schema):
    #: `missing` | `partial` | `ok` (sw-design.md §14.2).
    status: str
    language: str
    codes: list[CodeUsageResponse] = Field(default_factory=list)
    labelled_count: int
    total_count: int
    coverage_pct: float


class ColumnMappingResponse(_Schema):
    """One row of the Codelists master list."""

    corpus_id: str
    table_name: str
    column_name: str
    distinct_in_corpus: int
    mapping_id: str | None = None
    mapped_attribute: CodeAttributeResponse | None = None
    coverage: ColumnCoverageResponse | None = None
    #: Inert (always empty) until a feature exists to populate it (C5).
    used_by_features: list[str] = Field(default_factory=list)


class MapColumnRequest(_Schema):
    corpus_id: str
    source_column: str = Field(min_length=1, max_length=100)
    code_attribute_id: str


# ===========================================================================
# /api/v1/feature-configs  (F2)
#
# Base path is `/feature-configs`, not `/features` (plan-phase-2.md §3's P17
# table said the latter, §9's F2 section the former) — `/feature-configs`
# matches the resource this router actually roots on (`feature_config`, the
# thing created, frozen and cloned) and §9 is the more specific of the two.
# ===========================================================================


class DerivationFilterSchema(_Schema):
    """`(column, op, value)` — mvp-spec.md §8.3."""

    column: str
    #: `eq` | `ne` | `in` | `not_in` | `is_empty` | `is_not_empty`.
    operator: str
    value: list[str] | str | None = None


class DerivationSpecSchema(_Schema):
    """One of the seven closed-catalogue derivation types (mvp-spec.md §8.3).

    A loose envelope rather than seven distinct request models: `type`
    selects which of the remaining fields apply, the same discriminated shape
    `ra2.domain.feature.DerivationSpec` normalises into on the way in.
    """

    #: A `ra2.domain.feature.DerivationType` value.
    type: str
    #: `count_objects` / `count_persons` — optional; `any_object_matches` /
    #: `any_person_matches` — required.
    filter: DerivationFilterSchema | None = None
    #: `max_ordinal` / `min_ordinal` / `distinct_count` only.
    table: str | None = None
    column: str | None = None
    ordered_codes: list[str] | None = None


class MatchingRuleSchema(_Schema):
    #: `exact` | `within_tolerance` | `none`.
    kind: str
    tolerance_minutes: int | None = None
    decimal_precision: int | None = None


class FeatureRequest(_Schema):
    """Add or edit one feature. Draft configs only."""

    key: str = Field(min_length=1, max_length=100)
    #: `labelled` | `exploratory`.
    kind: str
    description: str
    #: `accident` | `derived` | `object` | `person`.
    grain: str
    source_column: str | None = None
    derivation: DerivationSpecSchema | None = None
    value_type: str
    matching_rule: MatchingRuleSchema


class FeatureResponse(_Schema):
    feature_id: str
    feature_config_id: str
    ordinal: int
    key: str
    kind: str
    description: str
    grain: str
    source_column: str | None = None
    derivation: DerivationSpecSchema | None = None
    value_type: str
    matching_rule: MatchingRuleSchema
    #: `None` until the enclosing set is frozen.
    fingerprint: str | None = None
    #: Always present — Q3's draft badge.
    fingerprint_preview: str
    #: Blocking validation messages; non-empty renders as an error row.
    #: Named to match `FeatureView.validation_errors` (§12.4's banned
    #: `errors=` keyword; Wave 2's amendment).
    validation_errors: list[str] = Field(default_factory=list)


class CreateFeatureConfigRequest(_Schema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class CloneFeatureConfigRequest(_Schema):
    """ "Clone to new evaluation" (design's C4) — a frozen set only."""

    name: str = Field(min_length=1, max_length=200)


class FeatureConfigResponse(_Schema):
    feature_config_id: str
    name: str
    version: int = 1
    description: str | None = None
    created_at: datetime
    frozen_at: datetime | None = None
    #: > 0 renders the `LOCKED · N eval` pill.
    locked_by_evaluations: int = 0
    features: list[FeatureResponse] = Field(default_factory=list)


class FeatureConfigSummaryResponse(_Schema):
    """One row of the feature-sets strip below the split."""

    feature_config_id: str
    name: str
    version: int = 1
    description: str | None = None
    created_at: datetime
    feature_count: int
    frozen_at: datetime | None = None
    locked_by_evaluations: int = 0


class FeatureValidationErrorResponse(_Schema):
    """422 from a blocked freeze. **Nothing was frozen** (mvp-spec.md §7/§8.2)."""

    detail: str = "blocking feature validation errors; the set was not frozen"
    #: Named to match `FeatureValidationError.validation_errors` (§12.4's
    #: banned `errors=` keyword; Wave 2's amendment).
    validation_errors: list[str]
