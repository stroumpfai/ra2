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
    "CorpusPage",
    "CorpusResponse",
    "CreateCorpusRequest",
    "DeliveryFileResponse",
    "DeliveryResponse",
    "ErrorResponse",
    "FileOverrideRequest",
    "FindingResponse",
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
