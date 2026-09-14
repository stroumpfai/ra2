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
from ra2.domain.llm import EndpointStatus, ProbeCode
from ra2.domain.prompt import PromptValidationCode, SlotName
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
    "ConnectionProbeResponse",
    "ConnectionResponse",
    "CorpusPage",
    "CorpusResponse",
    "CreateCorpusRequest",
    "CreateEvaluationRequest",
    "CreateFeatureConfigRequest",
    "CreatePromptTemplateRequest",
    "DeliveryFileResponse",
    "DeliveryResponse",
    "DerivationFilterSchema",
    "DerivationSpecSchema",
    "ErrorResponse",
    "EvaluationDraftResponse",
    "EvaluationLaunchResponse",
    "EvaluationResponse",
    "FeatureConfigResponse",
    "FeatureConfigSummaryResponse",
    "FeatureRequest",
    "FeatureResponse",
    "FeatureValidationErrorResponse",
    "FileOverrideRequest",
    "FindingResponse",
    "MapColumnRequest",
    "MatchingRuleSchema",
    "ModelCatalogResponse",
    "ModelChoiceResponse",
    "PageMeta",
    "ProfileBucketResponse",
    "PromptTemplateResponse",
    "PromptValidationErrorResponse",
    "PromptValidationIssueResponse",
    "ProvenanceResponse",
    "RegisterDeliveryRequest",
    "ResolvePromptRequest",
    "ResolvedPromptResponse",
    "RunPage",
    "RunProgressResponse",
    "RunResponse",
    "SelectFileRequest",
    "SlotResponse",
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
