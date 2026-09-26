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
from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.findings import FindingCode, Severity
from ra2.domain.llm import DEFAULT_REASONING_EFFORT, EndpointStatus, ProbeCode
from ra2.domain.mismatch import MismatchTag, TagFilter
from ra2.domain.prompt import PromptValidationCode, SlotName
from ra2.domain.qualification import QualificationState
from ra2.infra.tasks import TaskStatus
from ra2.services.readmodels import SortDir

__all__ = [
    "AnalyseResponse",
    "BlockingFindingsResponse",
    "BreakdownResponse",
    "BreakdownRowResponse",
    "ByLanguageResponse",
    "ByLanguageRowResponse",
    "CellResponse",
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
    "ConnectionProbeResponse",
    "ConnectionResponse",
    "CorpusPage",
    "CorpusResponse",
    "CreateCorpusRequest",
    "CreateEvaluationRequest",
    "CreateFeatureConfigRequest",
    "CreatePromptTemplateRequest",
    "CrossTabResponse",
    "DeliveryFileResponse",
    "DeliveryResponse",
    "DerivationFilterSchema",
    "DerivationSpecSchema",
    "DiscardPreview",
    "DiscardResponse",
    "ErrorResponse",
    "EvaluationDraftResponse",
    "EvaluationLaunchResponse",
    "EvaluationResponse",
    "ExtractionTabResponse",
    "FeatureConfigResponse",
    "FeatureConfigSummaryResponse",
    "FeatureRequest",
    "FeatureResponse",
    "FeatureScorePage",
    "FeatureScoreResponse",
    "FeatureValidationErrorResponse",
    "FileOverrideRequest",
    "FindingResponse",
    "FlagInconsistencyResponse",
    "Goal1CompanionResponse",
    "MapColumnRequest",
    "MatchingRuleSchema",
    "MismatchFeatureResponse",
    "MismatchFiltersResponse",
    "MismatchListResponse",
    "MismatchPage",
    "MismatchResponse",
    "ModelCatalogResponse",
    "ModelChoiceResponse",
    "ModelColumnResponse",
    "PageMeta",
    "PerRecordPage",
    "PerRecordResponse",
    "PresenceRowResponse",
    "PresenceTabResponse",
    "ProfileBucketResponse",
    "PromptTemplateResponse",
    "PromptValidationErrorResponse",
    "PromptValidationIssueResponse",
    "ProvenanceResponse",
    "QualificationCardResponse",
    "RankingRowResponse",
    "RankingTabResponse",
    "RegisterDeliveryRequest",
    "ResolvePromptRequest",
    "ResolvedPromptResponse",
    "ReviewTallyResponse",
    "RunDescriptorResponse",
    "RunPage",
    "RunProgressResponse",
    "RunResponse",
    "ScoringStatusResponse",
    "SelectFileRequest",
    "SeparatingRowResponse",
    "SlotResponse",
    "TagMismatchRequest",
    "TaskAcceptedResponse",
    "TaskProgressResponse",
    "TestConnectionRequest",
    "UpdateEvaluationRequest",
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
    #: True when the column has stored values and the sample rule withheld them
    #: (risk B1). Without it an empty `top_values` is ambiguous with a column
    #: that is empty in every row, which is the opposite conclusion.
    top_values_withheld: bool = False
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
    #: mvp-spec.md §7's "a Finding carrying the column, the value and the
    #: record key" — always `[]` when `in_codelist` is `true`.
    record_keys: list[str] = Field(default_factory=list)


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


# ===========================================================================
# /api/v1/prompt-templates  (K1)
#
# There is deliberately **no PATCH model** here: saving is copy-on-write, and
# the absence of an update shape is part of the contract (sw-design.md §15.1).
# ===========================================================================


class PromptTemplateResponse(_Schema):
    """One version of the prompt template."""

    prompt_template_id: str
    version: int
    source: str
    created_at: datetime
    is_active: bool = False
    #: `COUNT(run WHERE prompt_template_id = …)` — what makes `deletable` and
    #: the design's `locked` marker true rather than advisory.
    cited_by_run_count: int = 0
    fingerprint: str
    deletable: bool = True


class SlotResponse(_Schema):
    """One row of the "Slots available" reference strip."""

    name: SlotName
    token: str
    required: bool
    resolves_to: str = ""


class CreatePromptTemplateRequest(_Schema):
    """ "Save as vN". The version is assigned by the store, never by the
    caller, so two concurrent saves cannot pick the same integer."""

    source: str = Field(min_length=1)


class PromptValidationIssueResponse(_Schema):
    """One reason a template was refused. `code` is the stable identifier;
    wording lives in one rendering table in `ui/`."""

    code: PromptValidationCode
    slot: str | None = None
    offset: int | None = None


class PromptValidationErrorResponse(_Schema):
    """422 from a refused save. **Nothing was written** (sw-design.md §15.1)."""

    detail: str = "invalid prompt template; nothing was saved"
    #: Named to match `PromptTemplateInvalidError.validation_errors` — §12.4's
    #: banned `errors=` keyword, same as the two phase-2 error shapes.
    validation_errors: list[PromptValidationIssueResponse]


class ResolvePromptRequest(_Schema):
    """Expand a template against a feature set and one record.

    **Makes no model call** — both preview entry points land here (C4).
    """

    prompt_template_id: str
    feature_config_id: str
    record_id: str
    language: str = "de"


class ResolvedPromptResponse(_Schema):
    text: str
    #: Rendered `≈ N tokens`. An **estimate**: an exact count needs the
    #: model's tokeniser and every tokeniser package downloads its vocabulary,
    #: which is egress (N1). The real counts come back per call (C6).
    token_estimate: int
    record_key: str = ""
    feature_count: int = 0
    slots_used: list[SlotName] = Field(default_factory=list)
    validation_errors: list[PromptValidationIssueResponse] = Field(default_factory=list)


# ===========================================================================
# /api/v1/evaluations, /api/v1/runs, /api/v1/models  (K2)
# ===========================================================================


class QualificationCardResponse(_Schema):
    """What this host measured about one model (SD40): the Models card's
    third line. **Read-only.** There is no endpoint that records a
    qualification: that's `just qualify-model`'s job, and a `POST` taking
    numbers would let anything claim a measurement.

    `parallel_calls` is what a launch would pin today, not the map's value.
    `estimated_ms` is `null` without an evaluation to scope it.
    """

    state: QualificationState
    measured_digest: str
    seed_macro_f1: float
    ms_per_record: float
    entity_fill: float
    parallel_calls: int
    launch_ms_per_record: float
    estimated_ms: int | None = None


class ModelChoiceResponse(_Schema):
    """One row of the Models card.

    `fits_vram` is `null` when the host's VRAM is unknown — not a failure:
    every model stays selectable and the design's disabled row does not occur.
    """

    tag: str
    digest: str
    size_bytes: int
    fits_vram: bool | None = None
    selected: bool = False
    qualification: QualificationCardResponse | None = None


class ConnectionResponse(_Schema):
    """The endpoint line under the Models card.

    An unreachable endpoint is **200 with `reachable: false`**, never a 502:
    the UI renders the reason beside the endpoint line and disables Launch,
    and an error status would force exactly the toast the design rejects.
    """

    endpoint: str
    status: EndpointStatus
    reachable: bool
    timeout_s: int
    reason: str | None = None
    gpu_name: str | None = None
    gpu_vram_bytes: int | None = None


class TestConnectionRequest(_Schema):
    """`POST /api/v1/models/test` — probe an endpoint that is **not**
    configured.

    `endpoint` is deliberately a free string and **not** validated by Pydantic
    into a loopback URL: the refusal is the answer this route exists to give,
    so rejecting it at the schema would turn the most interesting result into
    a 422 the dialog cannot render.

    `timeout_s` omitted means the configured `RA2_LLM_TIMEOUT_S`; either way
    the probe lowers it to its own cap and reports the bound it used.
    """

    endpoint: str = Field(min_length=1, max_length=2000)
    timeout_s: int | None = Field(default=None, ge=1)


class ConnectionProbeResponse(_Schema):
    """One connection test's outcome. **Always 200**, whatever `code` says.

    The same reasoning that makes an unreachable endpoint `200` with
    `reachable: false` on `GET /models`: a probe that found nothing has
    succeeded at its job, and an error status would force exactly the toast
    the design rejects. `detail` is the provider's or the OS's verbatim words
    and `code` is the stable identifier — clients render from `code`.
    """

    endpoint: str
    code: ProbeCode
    ok: bool
    detail: str | None = None
    latency_ms: int | None = None
    model_count: int | None = None
    http_status: int | None = None
    probe_timeout_s: int = 0


class ModelCatalogResponse(_Schema):
    """`GET /api/v1/models` — the catalogue and the connection, together."""

    connection: ConnectionResponse
    models: list[ModelChoiceResponse] = Field(default_factory=list)


class CreateEvaluationRequest(_Schema):
    """ "Save draft" for a new evaluation. Everything else takes the design's
    defaults: the active template, temperature 0.0, seed 42, size `full`."""

    name: str = Field(min_length=1, max_length=200)
    corpus_id: str
    feature_config_id: str


class UpdateEvaluationRequest(_Schema):
    """Edit any of the six setup steps. **Draft only** — editing a launched
    evaluation is 409."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    corpus_id: str | None = None
    feature_config_id: str | None = None
    prompt_template_id: str | None = None
    prompt_language: str | None = Field(default=None, max_length=16)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    seed: int | None = None
    #: One of `domain.llm.REASONING_EFFORTS`. **Not a `Literal`**: the refusal
    #: an unmappable effort deserves is `EvaluationService`'s 422, a sentence
    #: naming the four it could have been, and a `Literal` would answer with a
    #: schema error that names the field instead of the repair.
    reasoning_effort: str | None = Field(default=None, max_length=16)
    size: EvaluationSize | None = None
    selected_models: list[str] | None = None


class EvaluationDraftResponse(_Schema):
    """An evaluation's setup — the six numbered steps, as data."""

    evaluation_id: str
    name: str
    corpus_id: str
    feature_config_id: str
    prompt_template_id: str | None = None
    prompt_language: str = "de"
    temperature: float = 0.0
    seed: int = 42
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    size: EvaluationSize = EvaluationSize.FULL
    selected_models: list[str] = Field(default_factory=list)
    launched_at: datetime | None = None


class RunProgressResponse(_Schema):
    """One per-model progress card. Every count is derived from committed
    `extraction` rows, never from a counter column (§15 F6)."""

    run_id: str
    model_tag: str
    status: RunStatus
    done: int = 0
    total: int = 0
    percent: float = 0.0
    parse_failures: int = 0
    #: mvp-spec.md §10.4 — bounded **and** counted.
    retries: int = 0
    median_latency_ms: int | None = None
    prompt_tokens: int = 0
    elapsed_ms: int | None = None
    eta_ms: int | None = None


class RunResponse(_Schema):
    """One row of the "Runs in this evaluation" table."""

    run_id: str
    evaluation_id: str
    model_tag: str
    model_digest: str
    records_done: int = 0
    started_at: datetime | None = None
    status: RunStatus
    #: mvp-spec.md §9 — every view showing this run's numbers carries the
    #: "smoke test, not a result" marker.
    is_dev: bool = False
    error: str | None = None


class RunPage(_Schema):
    items: list[RunResponse]
    meta: PageMeta


class ProvenanceResponse(_Schema):
    """mvp-spec.md §19.8 — "every run's record alone is sufficient to
    reproduce it"."""

    model_name: str
    model_digest: str
    prompt_template_version: int
    prompt_template_fingerprint: str
    temperature: float
    seed: int
    feature_config_id: str
    #: `{feature key: fingerprint}` from `evaluation_feature` — the real ones,
    #: resolved in the launch transaction, not draft previews.
    feature_fingerprints: dict[str, str] = Field(default_factory=dict)
    corpus_id: str
    corpus_version: int
    host_platform: str
    gpu_name: str | None = None
    llm_endpoint: str
    #: `None` on a run written before the field existed — "not
    #: recorded", never a guessed default.
    llm_reasoning_effort: str | None = None
    #: Records this run kept in flight (SD38); `1` on every earlier run.
    llm_parallel_calls: int = 1


class EvaluationResponse(_Schema):
    """One whole Evaluation screen."""

    draft: EvaluationDraftResponse
    connection: ConnectionResponse
    models: list[ModelChoiceResponse] = Field(default_factory=list)
    progress: list[RunProgressResponse] = Field(default_factory=list)
    runs: RunPage | None = None
    provenance: ProvenanceResponse | None = None
    feature_config_label: str = ""
    corpus_label: str = ""
    corpus_record_count: int = 0
    dev_record_max: int = 0
    can_launch: bool = False


class TaskAcceptedResponse(_Schema):
    """Work was submitted; poll `GET /api/v1/tasks/{task_id}`."""

    task_id: str


class EvaluationLaunchResponse(_Schema):
    """The launch commit, plus the task the worker runs under.

    Two things in one response because they happen together and the view
    needs both: the pinned evaluation to render, and the task id to poll.
    """

    evaluation: EvaluationResponse
    task_id: str


# ---------------------------------------------------------------------------
# Results — phase 4 (U1, U2). mvp-spec.md §11, sw-design.md §16.7.
#
# The one rule this section adds to the boundary: **a suppressed cell never
# serialises as a number.** `CellResponse` is a tagged union in one field —
# `suppressed: true` carries `n` and `floor` and leaves `value` absent — so a
# client that forgets to check the flag gets `null`, not a plausible figure
# nobody measured (mvp-spec.md §11.4, SD19).
# ---------------------------------------------------------------------------


class CellResponse(_Schema):
    """One cell: either a measurement, or the reason there is not one."""

    suppressed: bool
    #: The labelled-case count. Present either way — §11.4 requires every
    #: metric to be rendered with its `n`, and the suppression notice states it.
    n: int
    #: `None` **exactly when** `suppressed` is true. Never `0.0` there.
    value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    #: `best` / `tied` / `none`, the shape-coded tie marker (P4-D2).
    mark: str = "none"
    #: The evaluation's own floor, so a client renders "below the minimum of
    #: N" from data rather than from a literal (SD19).
    floor: int | None = None


class RunDescriptorResponse(_Schema):
    """The identity line every tab carries — "a score without its config is
    not a result"."""

    evaluation_id: str
    corpus_label: str
    record_count: int
    model_count: int
    config_fingerprint: str
    #: mvp-spec.md §13: the "smoke test, not a result" marker is required on
    #: **every** dev-sized result wherever its numbers appear.
    is_dev: bool
    min_cell_count: int


class ModelColumnResponse(_Schema):
    model_id: str
    tag: str
    digest: str


class FeatureScoreResponse(_Schema):
    feature_id: str
    name: str
    source_label: str
    n: int
    suppressed: bool
    cells: dict[str, CellResponse]


class FeatureScorePage(_Schema):
    items: list[FeatureScoreResponse]
    total: int
    page: int
    page_size: int
    sort_key: str
    sort_dir: SortDir


class BreakdownRowResponse(_Schema):
    model_id: str
    precision: float
    recall: float
    f1: float
    #: Stored, not back-derived from P and R (SD18).
    hit: int
    wrong: int
    missing: int


class BreakdownResponse(_Schema):
    feature_id: str
    feature_name: str
    rows: list[BreakdownRowResponse]


class ByLanguageRowResponse(_Schema):
    language: str
    cell: CellResponse


class ByLanguageResponse(_Schema):
    feature_id: str
    feature_name: str
    model_id: str
    rows: list[ByLanguageRowResponse]


class ExtractionTabResponse(_Schema):
    """Tab 1. `scored` is `false` on a run nobody has scored yet — **200, not
    404** (§16.7): the UI renders a state, and an error status would force the
    toast the design rejects."""

    scored: bool
    descriptor: RunDescriptorResponse
    models: list[ModelColumnResponse]
    features: FeatureScorePage
    breakdown: BreakdownResponse | None = None
    by_language: ByLanguageResponse | None = None


class ScoringStatusResponse(_Schema):
    run_id: str
    scored_features: int
    labelled_features: int
    running: bool
    is_scored: bool
    #: `False` means there is nothing to score — every feature is exploratory.
    #: Distinct from "every feature is suppressed", which **is** scoreable and
    #: renders as suppression (§16.7).
    is_scoreable: bool


class Goal1CompanionResponse(_Schema):
    """mvp-spec.md §11.2: "Goal 2 numbers are never published without the
    corresponding Goal 1 numbers."

    A **required** field on `PresenceRowResponse`, not an optional one, so the
    wire format cannot drop the column the read model is careful to carry.
    """

    f1: float
    precision: float
    recall: float


class PresenceRowResponse(_Schema):
    feature_key: str
    rates: dict[str, CellResponse]
    goal1: Goal1CompanionResponse


class CrossTabResponse(_Schema):
    feature_key: str
    model_id: str
    hit_present: int
    #: The self-contradiction cell: the model said the text does not contain
    #: the feature and then extracted the record's exact value from it.
    hit_absent: int
    wrong_present: int
    wrong_absent: int
    missing_present: int
    missing_absent: int


class FlagInconsistencyResponse(_Schema):
    model_id: str
    cell: CellResponse


class PerRecordResponse(_Schema):
    record_id: str
    #: Required wherever text is shown (mvp-spec.md §13).
    anonymised: bool
    record_value: str
    finding: str
    language: str
    language_confidence: float


class PerRecordPage(_Schema):
    items: list[PerRecordResponse]
    total: int
    page: int
    page_size: int


class PresenceTabResponse(_Schema):
    scored: bool
    descriptor: RunDescriptorResponse
    models: list[ModelColumnResponse]
    model_id: str
    rows: list[PresenceRowResponse]
    cross_tab: CrossTabResponse | None = None
    flag_inconsistency: list[FlagInconsistencyResponse] = Field(default_factory=list)
    records: PerRecordPage | None = None


class RankingRowResponse(_Schema):
    model_id: str
    tag: str
    digest: str
    #: **Shared on a tie** (`1, 1, 3`), never dense (§11.5).
    rank: int
    macro_f1: float
    ci_low: float
    ci_high: float
    best: int
    tied: int
    worse: int
    verdict: str
    #: Reported, never scored — and neither are the four below (SD20).
    presence_rate: float
    median_latency_ms: int
    prompt_tokens: int
    #: Reported, never scored (SD38): mean latency ÷ parallel calls.
    ms_per_record: int = 0
    parallel_calls: int = 1
    #: Reported, never scored (SD41): the size the endpoint reported for this
    #: run's tag at launch, which the Ranking tab renders as VRAM. `None` for a
    #: run launched before the column existed — **not** `0`, which is what this
    #: field carried, hard-coded, before SD41.
    model_size_bytes: int | None = None


class SeparatingRowResponse(_Schema):
    feature_id: str
    name: str
    source_label: str
    n: int
    f1_by_model: dict[str, float]
    delta: float
    reading: str


class RankingTabResponse(_Schema):
    """Tab 3. An evaluation where every feature is suppressed returns this
    shape with empty `rows` **and** a verdict saying so — never a bare empty
    list, which a UI renders as a blank table (§16.7)."""

    scored: bool
    descriptor: RunDescriptorResponse
    rows: list[RankingRowResponse]
    separating: list[SeparatingRowResponse]
    verdict_headline: str
    verdict_detail: str
    scored_feature_count: int
    unscored_feature_count: int


# ===========================================================================
# Reset and discard — sw-design.md §18
# ===========================================================================


class DiscardPreview(_Schema):
    """What a discard would destroy, counted before anything is destroyed.

    One shape for all three kinds (§18.5), mirroring `DiscardPreviewView`
    field-for-field plus its two computed properties — the wire format carries
    them as data so a client does not re-derive a rule the service owns.
    """

    kind: str
    target_id: str
    label: str
    runs: int
    extractions: int
    scores: int
    mismatches: int
    tagged_mismatches: int
    files: int
    #: G1 as a **state**, not an error: a caller has to be able to say "a run
    #: is still going" without provoking the 409 to find out.
    active: bool
    active_detail: str | None = None
    #: Corpora frozen from this delivery. Non-zero refuses outright — there is
    #: no `force` for this one (§18.2).
    cited_by: int = 0
    has_exportable: bool = False
    blocked: bool = False


class DiscardResponse(_Schema):
    """What a discard actually removed.

    A body rather than a bare `204`, because the counts are the only record
    that survives the call: nothing is written anywhere saying this happened
    (§18.3), so the response *is* the receipt.
    """

    kind: str
    target_id: str
    runs: int
    extractions: int
    scores: int
    mismatches: int
    tagged_mismatches: int
    files: int
    #: True when the caller overrode G2 — so a client that did not mean to
    #: force can tell that it did.
    forced: bool = False


# ===========================================================================
# Mismatch review — phase 5 (Y2). mvp-spec.md §12, sw-design.md §17
#
# The one rule this section adds to the boundary: **the wire vocabulary is
# closed even though the column is not** (`SD24`, §17.5). `TagMismatchRequest`
# takes a `MismatchTag`, so an unknown tag is a 422 from FastAPI rather than a
# silent write — while `MismatchResponse.analyst_tag` stays a plain string,
# because a value the enum does not name must still render as itself.
# ===========================================================================


class MismatchResponse(_Schema):
    """One row of the flat list.

    Carries no run: the list is one run at a time (§17.6), and the run is
    named once on `MismatchListResponse`.
    """

    mismatch_id: str
    record_id: str
    #: mvp-spec.md §13 — required wherever text is shown, and this row shows an
    #: evidence span.
    anonymised: bool
    feature_id: str
    feature_key: str
    record_value: str | None = None
    extracted_value: str | None = None
    evidence_span: str | None = None
    #: The **stored** value, verbatim. A tag `MismatchTag` does not name
    #: travels as itself rather than being nulled on the way out.
    analyst_tag: str | None = None
    tagged_at: datetime | None = None
    note: str | None = None
    #: The read model's narrowing, carried as data so a client does not
    #: re-derive a rule the service owns — the same treatment `DiscardPreview`
    #: gives `blocked`.
    tag: MismatchTag | None = None
    is_other: bool = False
    reviewed: bool = False


class MismatchPage(_Schema):
    items: list[MismatchResponse]
    total: int
    page: int
    page_size: int
    sort_key: str
    sort_dir: SortDir


class ReviewTallyResponse(_Schema):
    """One feature's review counts — §12's "of 40 reviewed, 32 hallucination,
    8 record error".

    `counts` is keyed by `MismatchTag` value and always carries all three, so
    a client cannot miss one that nobody has used yet. `other` is the bucket
    for a stored value the enum does not name (§17.5).
    """

    feature_id: str
    feature_key: str
    total: int
    reviewed: int
    untagged: int
    counts: dict[str, int]
    other: int


class MismatchFeatureResponse(_Schema):
    """One option of the Feature filter, and how much work is behind it."""

    feature_id: str
    feature_key: str
    total: int


class MismatchFiltersResponse(_Schema):
    """What the list was filtered by — echoed back, so a client can render the
    toolbar from the response rather than from what it thinks it asked for."""

    run_id: str
    feature_id: str | None = None
    tag_state: TagFilter


class MismatchListResponse(_Schema):
    """The whole screen.

    **An evaluation with no mismatches is 200 with an empty list**, never a
    404: "nothing was wrong" is a result, not an error (the §16.7 reasoning,
    reapplied).

    `run_finished_at` is `SD25`'s staleness anchor — a re-score can delete a
    tagged row, and this is the closest honest thing RA2 records to "when was
    this scored" (§17.7).
    """

    descriptor: RunDescriptorResponse
    runs: list[ModelColumnResponse]
    run_label: str
    run_finished_at: datetime | None = None
    features: list[MismatchFeatureResponse]
    filters: MismatchFiltersResponse
    rows: MismatchPage
    tallies: list[ReviewTallyResponse]


class TagMismatchRequest(_Schema):
    """**Where the closed half of `SD24` is enforced on the wire.**

    `tag` is a `MismatchTag`, so a value outside the three is a 422 from
    FastAPI's own validation and never reaches the column. The column stays
    `String(32)` so a fourth tag needs no migration; nothing in the MVP can
    write one, and that asymmetry is deliberate (§17.5).
    """

    tag: MismatchTag
    #: Optional and single-line. The column exists, the service writes it and
    #: the CSV carries it; nothing in mvp-spec.md §12 describes more.
    note: str | None = None
