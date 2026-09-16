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
from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import DerivationSpec, Grain, Kind, MatchingRule, ValueType
from ra2.domain.findings import Finding
from ra2.domain.ids import (
    CensusColumnId,
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    DeliveryId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    FileId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.llm import EndpointStatus, ProbeCode
from ra2.domain.prompt import PromptValidationError, SlotName
from ra2.domain.stats import TieMark

__all__ = [
    "BreakdownRowView",
    "BreakdownView",
    "ByLanguageRow",
    "ByLanguageView",
    "CatalogueView",
    "Cell",
    "CensusBucket",
    "CensusColumnView",
    "CensusSummary",
    "CodeAttributeView",
    "CodelistImportResult",
    "ColumnMappingView",
    "ConnectionProbeView",
    "ConnectionView",
    "CorpusSummary",
    "CorpusView",
    "CrossTabView",
    "DataDirView",
    "DeliveryFileView",
    "DeliveryView",
    "DiscardPreviewView",
    "EvaluationDraftView",
    "EvaluationView",
    "ExploratoryRow",
    "ExtractionTabView",
    "FeatureConfigView",
    "FeatureScoreRow",
    "FeatureSetSummary",
    "FeatureView",
    "FlagInconsistencyRow",
    "Goal1Companion",
    "MetricCell",
    "MismatchExportRow",
    "ModelChoiceView",
    "ModelColumnView",
    "Page",
    "PerRecordRow",
    "PresenceRow",
    "PresenceTabView",
    "PromptTemplateView",
    "ProvenanceView",
    "RankingRow",
    "RankingTabView",
    "ResolvedPromptView",
    "RunDescriptorView",
    "RunExportView",
    "RunProgressView",
    "RunView",
    "ScoreExportRow",
    "ScoringStatusView",
    "SeparatingRow",
    "SlotView",
    "SortDir",
    "SuppressedCell",
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
    #: render as errors and block "Create a feature set". Named to match
    #: `FeatureValidationError.validation_errors`, which avoids the banned
    #: `errors=` keyword for the same reason (§12.4) — Wave 2's amendment
    #: (contracts/amendments/feat-p2-feature-service.md) finishes a rename
    #: Wave 0 started in `services/errors.py` but missed here.
    validation_errors: tuple[str, ...] = ()


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


# ===========================================================================
# Prompts (F5) — phase 3, mvp-spec.md §10.2, sw-design.md §15.1,
# design/prompt-evaluation/README.md §1.
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PromptTemplateView:
    """One row of the Prompts version list, and the editor's content for it.

    The four row markers the design draws come from three fields: `is_active`
    -> the `ACTIVE` pill and the selected-row treatment; `cited_by_run_count`
    > 0 with `is_active` false -> `locked`; `deletable` -> the `--danger`
    delete button.
    """

    prompt_template_id: PromptTemplateId
    version: int
    #: The template text, verbatim. The Source card highlights `{{slots}}` in
    #: it; the highlighting is presentation, the text is not touched.
    source: str
    created_at: datetime
    is_active: bool
    #: The design's ".rsub" line, "created · citation count".
    cited_by_run_count: int
    fingerprint: str

    @property
    def deletable(self) -> bool:
        """Only a version with zero runs can be deleted; all others show
        `locked` (sw-design.md §15.1)."""
        return self.cited_by_run_count == 0


@dataclass(frozen=True, slots=True)
class SlotView:
    """One row of the "Slots available" reference strip.

    `resolves_to` is the design's per-slot description, already resolved
    against the current context where there is one — "13 features",
    "record text", "de". The view renders it; it never computes it.
    """

    name: SlotName
    token: str
    required: bool
    resolves_to: str


@dataclass(frozen=True, slots=True)
class ResolvedPromptView:
    """The shared preview panel's content (plan-phase-3.md C4).

    **One component, two entry points**: Prompts' "Preview with record 1"
    resolves against the active feature set and record 1; Evaluation's
    "Preview prompt" resolves against its own pinned inputs. Neither makes a
    model call.
    """

    text: str
    #: Rendered as `≈ N tokens` — an **estimate**, and the UI says so. The
    #: real counts come back from the endpoint per call (C6).
    token_estimate: int
    #: The design's header line, "Resolved — record 1, all 13 features".
    record_key: str
    feature_count: int
    slots_used: tuple[SlotName, ...] = ()
    #: Non-empty when the template being previewed would not save. The
    #: preview still renders — seeing the broken expansion is the point.
    validation_errors: tuple[PromptValidationError, ...] = ()


# ===========================================================================
# Evaluation (F6) — phase 3, mvp-spec.md §9, sw-design.md §15.2,
# design/prompt-evaluation/README.md §2.
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ModelChoiceView:
    """One row of the Models card (the design's step 4).

    `fits_vram` is `None` when the host's VRAM is unknown — no NVIDIA GPU, no
    NVML, no override. That is **not** a failure: every model stays
    selectable and the design's disabled row simply does not occur
    (sw-design.md §15.6).
    """

    tag: str
    digest: str
    size_bytes: int
    fits_vram: bool | None
    selected: bool = False

    @property
    def disabled(self) -> bool:
        """`opacity:.55` with the size line in `--warn` — only when we
        actually know the model does not fit."""
        return self.fits_vram is False


@dataclass(frozen=True, slots=True)
class ConnectionView:
    """The endpoint line under the Models card, and the settings dialog's
    three controls (Q4).

    `reason` is rendered **beside the endpoint line, never as a toast**, and
    an unreachable endpoint **disables Launch** (plan-phase-3.md C3).
    """

    endpoint: str
    status: EndpointStatus
    timeout_s: int
    #: `None` when reachable. A sentence for the analyst, from one rendering
    #: table in `ui/` keyed on `status` — not a provider error string.
    reason: str | None = None
    #: The probe's answer, for the reproducibility card and the VRAM
    #: judgement. `None` is the honest "unknown".
    gpu_name: str | None = None
    gpu_vram_bytes: int | None = None

    @property
    def is_reachable(self) -> bool:
        return self.status is EndpointStatus.REACHABLE


@dataclass(frozen=True, slots=True)
class CatalogueView:
    """What the Models card needs when there is **no evaluation yet**.

    The card mixes two different things, and they have different owners: which
    models the endpoint has — with their digests, sizes and VRAM judgement —
    is a property of the **endpoint**, while the ticks are a property of the
    **evaluation**. `EvaluationView` carries both, which is right once an
    evaluation exists and is why the card rendered nothing before one did: the
    half that never depended on an evaluation was reached through the half
    that did.

    Deliberately the same two field names `EvaluationView` uses, so the view
    reads one shape either way and the difference stays where it belongs —
    whether the rows are selectable.
    """

    connection: ConnectionView
    models: tuple[ModelChoiceView, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectionProbeView:
    """One connection test, as the settings dialog renders it.

    Distinct from `ConnectionView`, which describes the **configured**
    endpoint in one bit for the Models card. This describes an endpoint the
    analyst has *typed* and pressed Test on, and it carries a named cause,
    because "unreachable" cannot separate "Ollama is not running" from "that
    is the wrong port" — and separating those is the whole point of the
    button.

    Note what is **not** here: a sentence. `code` is the stable identifier and
    the wording lives in one rendering table in `ui/`, exactly as `FindingCode`
    does (CLAUDE.md). `ConnectionView.reason` is a sentence because it predates
    this and is shared with the API's own response; new work follows the rule.
    """

    endpoint: str
    code: ProbeCode
    #: The provider's or the OS's verbatim words, rendered as a second,
    #: monospaced line under the sentence. `None` when there were none.
    detail: str | None = None
    latency_ms: int | None = None
    model_count: int | None = None
    http_status: int | None = None
    #: The bound the probe actually used — the *lower* of the configured
    #: timeout and the probe's own cap. `TIMEOUT`'s sentence names it, so a
    #: 5-second failure does not read as contradicting the 120 in the field
    #: above it.
    probe_timeout_s: int = 0

    @property
    def ok(self) -> bool:
        return self.code is ProbeCode.OK


@dataclass(frozen=True, slots=True)
class EvaluationDraftView:
    """An evaluation's **setup** — the six numbered steps, as data.

    Editable while `launched_at` is `None`; every edit path raises
    `EvaluationLockedError` after (sw-design.md §15.2).
    """

    evaluation_id: EvaluationId
    name: str
    corpus_id: CorpusId
    feature_config_id: FeatureConfigId
    prompt_template_id: PromptTemplateId | None
    prompt_language: str
    temperature: float
    seed: int
    size: EvaluationSize
    selected_models: tuple[str, ...] = ()
    launched_at: datetime | None = None

    @property
    def is_launched(self) -> bool:
        return self.launched_at is not None

    @property
    def launch_label_count(self) -> int:
        """The primary button reads "Launch N runs", and N follows the model
        selection."""
        return len(self.selected_models)


@dataclass(frozen=True, slots=True)
class RunProgressView:
    """One per-model progress card (the design's progress column).

    Every count here is **derived from committed `extraction` rows**, never
    from a counter column (§15 F6): a counter is a second source of truth that
    a restart can disagree with. A `queued` model renders with a 0 % bar and
    **no metrics line** — there is nothing honest to put in it yet.
    """

    run_id: RunId
    model_tag: str
    status: RunStatus
    done: int
    total: int
    parse_failures: int = 0
    retries: int = 0
    median_latency_ms: int | None = None
    prompt_tokens: int = 0
    elapsed_ms: int | None = None
    eta_ms: int | None = None

    @property
    def percent(self) -> float:
        """0-100, clamped. The `.bar` fill width."""
        if self.total <= 0:
            return 0.0
        return min(100.0, max(0.0, 100.0 * self.done / self.total))

    @property
    def has_metrics(self) -> bool:
        return self.status is not RunStatus.QUEUED


@dataclass(frozen=True, slots=True)
class RunView:
    """One row of the "Runs in this evaluation" table.

    `is_dev` paints the row `--warn-soft` and every downstream view must label
    it "smoke test, not a result" (mvp-spec.md §9). A `FAILED` row paints
    `--danger-soft` and offers a muted "log" action instead of "results".
    """

    run_id: RunId
    evaluation_id: EvaluationId
    model_tag: str
    model_digest: str
    records_done: int
    started_at: datetime | None
    status: RunStatus
    is_dev: bool = False
    #: Why it failed — the "log" action's content. `None` unless `FAILED`.
    error: str | None = None

    @property
    def is_resumable(self) -> bool:
        """An interrupted run is resumed **explicitly**; nothing auto-restarts
        at startup (§15 F8)."""
        return self.status is RunStatus.INTERRUPTED


@dataclass(frozen=True, slots=True)
class ProvenanceView:
    """ "Stored on every run — enough to reproduce it" (mvp-spec.md §19.8).

    Every field the acceptance criterion names, in the order the design's
    reproducibility card lists them. If a field here is `None`, the run is not
    reproducible and the card must say so rather than omit the line.
    """

    model_name: str
    model_digest: str
    prompt_template_version: int
    prompt_template_fingerprint: str
    temperature: float
    seed: int
    feature_config_id: FeatureConfigId
    #: `{feature key: fingerprint}` from `evaluation_feature` — the real
    #: fingerprints, resolved in the launch transaction, not draft previews.
    feature_fingerprints: Mapping[str, str]
    corpus_id: CorpusId
    corpus_version: int
    host_platform: str
    gpu_name: str | None
    llm_endpoint: str


@dataclass(frozen=True, slots=True)
class EvaluationView:
    """A whole evaluation screen's worth of data: setup, models, connection,
    progress, runs and provenance.

    One read model rather than six service calls, for the same reason
    `DeliveryView` carries its files: the view renders one screen and must not
    assemble it from parts that could disagree.
    """

    draft: EvaluationDraftView
    connection: ConnectionView
    models: tuple[ModelChoiceView, ...] = ()
    progress: tuple[RunProgressView, ...] = ()
    runs: Page[RunView] | None = None
    #: `None` until a run exists — provenance is written at run start.
    provenance: ProvenanceView | None = None
    #: The toolbar's pinned-inputs line, "Weather & conditions · v2 — only the
    #: model varies".
    feature_config_label: str = ""
    corpus_label: str = ""
    #: What step 6 offers: the corpus's record count, and the dev cap from
    #: `RA2_DEV_RECORD_MAX`. The design's "Dev · 40 records" reads its number
    #: from config, never from a literal.
    corpus_record_count: int = 0
    dev_record_max: int = 0

    @property
    def can_launch(self) -> bool:
        """An unreachable endpoint **disables Launch**, with the reason
        rendered beside the endpoint line (plan-phase-3.md C3)."""
        return (
            self.connection.is_reachable
            and bool(self.draft.selected_models)
            and self.draft.prompt_template_id is not None
            and not self.draft.is_launched
        )


# ===========================================================================
# Results — phase 4 (M27), sw-design.md §16.7. One route, three tabs, one
# evaluation.
#
# Two rules here are expressed as **shapes** rather than as conventions,
# because a convention is what a later refactor drops:
#
#   - a suppressed cell is `SuppressedCell`, which has no `value` field at
#     all. It cannot be formatted into a string by accident and it cannot be
#     sorted as zero (SD19, §16.4).
#   - `PresenceRow` carries its `goal1` block and there is no constructor that
#     omits it. "Goal 2 numbers are never published without the Goal 1 numbers
#     beside them" (§11.2) is then a type error rather than a review comment.
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SuppressedCell:
    """A cell below the evaluation's floor — `mvp-spec.md` §11.4.

    **Carries no value, by construction.** "Cells with n below the minimum
    count render as 'insufficient data', **never as a number**", and the
    cheapest way to keep that true through four layers is for the number not to
    exist in the shape at all.

    `n` and `floor` are both here because the notice states them — "17 labelled
    cases, below the minimum of 20" — and the floor is per-evaluation (`SD19`),
    so a renderer must not reach for a constant.
    """

    n: int
    floor: int


@dataclass(frozen=True, slots=True)
class MetricCell:
    """A point estimate with its Wilson interval — `mvp-spec.md` §11.4's
    "every metric is rendered with its **n** and its interval"."""

    value: float
    ci_low: float
    ci_high: float
    n: int
    mark: TieMark = TieMark.NONE


#: Either a number or the reason there is no number. Every renderer must
#: handle both, which is the point: `MetricCell | None` would have let a
#: suppressed cell render as an empty string.
Cell = MetricCell | SuppressedCell


@dataclass(frozen=True, slots=True)
class RunDescriptorView:
    """The identity line every tab carries — "a score without its config is not
    a result" (`design/results/README.md`).

    `is_dev` is not decoration: `mvp-spec.md` §13 requires the "smoke test, not
    a result" marker on **every** dev-sized result wherever its numbers appear.
    On these boards it *replaces* the "Evaluation run" pill rather than sitting
    beside it, so there is no state in which a dev number renders unmarked.
    """

    evaluation_id: EvaluationId
    corpus_label: str
    record_count: int
    model_count: int
    #: The short `cfg` hash the design chips — the frozen feature config's
    #: fingerprint, not the evaluation's id.
    config_fingerprint: str
    is_dev: bool
    min_cell_count: int


@dataclass(frozen=True, slots=True)
class ModelColumnView:
    """One model column header: the tag, and the digest that is its identity."""

    model_id: str
    tag: str
    digest: str


@dataclass(frozen=True, slots=True)
class BreakdownRowView:
    """One model's row of an expanded feature: P · R · F1 · hit · wrong · missing.

    Six `score` rows of one table, not a join (`SD18`). The counts are stored
    rather than back-derived from P and R, which is off by one exactly at small
    `n`.
    """

    model_id: str
    precision: float
    recall: float
    f1: float
    hit: int
    wrong: int
    missing: int


@dataclass(frozen=True, slots=True)
class BreakdownView:
    """The expanded row under one feature. One open at a time.

    `hallucination_note` is rendered verbatim and is a **spec guarantee**, not
    a caption: `D1` and §11.1's warning say a hallucination rate is not
    computable and must never be presented as if it were measured. It renders
    even though the mismatch list it points at is phase 5 — a promise the
    product keeps by not making a claim.
    """

    feature_id: FeatureId
    feature_name: str
    rows: tuple[BreakdownRowView, ...]


@dataclass(frozen=True, slots=True)
class FeatureScoreRow:
    """One feature's row of the extraction table: name, source, `n`, one cell
    per model.

    `cells` is keyed by `model_id` and every model column has an entry — a
    missing key would render as a gap that looks like a layout bug rather than
    like a missing measurement.

    `suppressed` is the row-level fact (`n` below the floor), which tints the
    row and replaces **all** the model cells with one notice. It is `True`
    exactly when every entry in `cells` is a `SuppressedCell`.
    """

    feature_id: FeatureId
    name: str
    #: `Witter0Ausw · enum`, or `derived · count_objects · integer`.
    source_label: str
    n: int
    suppressed: bool
    cells: Mapping[str, Cell]


@dataclass(frozen=True, slots=True)
class ByLanguageRow:
    """One language's cell for one feature × model (`mvp-spec.md` §11.1)."""

    language: str
    cell: Cell


@dataclass(frozen=True, slots=True)
class ByLanguageView:
    """The per-language breakdown, and the caveat it may never be shown without.

    `mvp-spec.md` §13 requires the language breakdown to carry "a **standing
    caveat** that encoding loss affects French more than German and cannot be
    quantified". It is part of this shape rather than of the template so that a
    breakdown cannot be rendered somewhere else without it.
    """

    feature_id: FeatureId
    feature_name: str
    model_id: str
    rows: tuple[ByLanguageRow, ...]


@dataclass(frozen=True, slots=True)
class ExploratoryRow:
    """One Goal 3 attribute — `no ground truth · not ranked` (`mvp-spec.md` §11.3).

    **There is no model dimension here, deliberately.** "Discovery rates are
    never compared between models as a quality signal — a freely hallucinating
    model wins this metric." The comparison is not merely undrawn; there is no
    shape that expresses it.

    `reviewed` / `review_total` are `None` for the whole of phase 4: the
    counter implies the tagging machinery F11 defers, and building a second one
    for exploratory attributes would duplicate it (plan-phase-4.md C6). The
    card renders `— / n` and names the deferral, never a fake zero.
    """

    attribute_key: FeatureId
    name: str
    discovery_rate: float
    evidence_span_count: int
    reviewed: int | None = None
    review_total: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractionTabView:
    """Tab 1 — the only tab with ground truth, and the input every other tab is
    read against."""

    descriptor: RunDescriptorView
    models: tuple[ModelColumnView, ...]
    features: Page[FeatureScoreRow]
    #: The open breakdown, if any. One at a time.
    breakdown: BreakdownView | None = None
    by_language: ByLanguageView | None = None
    exploratory: tuple[ExploratoryRow, ...] = ()


@dataclass(frozen=True, slots=True)
class Goal1Companion:
    """The Goal 1 numbers that travel with every presence row.

    `mvp-spec.md` §11.2: "Goal 2 numbers are **never published without the
    corresponding Goal 1 numbers** — a weak extractor manufactures false
    'missing' flags." A separate type, required by `PresenceRow`, so dropping
    the column is a type error and not an edit.
    """

    f1: float
    precision: float
    recall: float


@dataclass(frozen=True, slots=True)
class PresenceRow:
    """One feature's presence rates, per language, with its Goal 1 companions."""

    feature_key: str
    #: Keyed by language, plus `domain.scoring.ALL_LANGUAGES` for the
    #: all-languages column.
    rates: Mapping[str, Cell]
    goal1: Goal1Companion


@dataclass(frozen=True, slots=True)
class CrossTabView:
    """Goal 1 outcome × presence, for one feature × model (`mvp-spec.md` §11.2).

    `hit_absent` is the card's whole point and is styled as the finding: the
    model said the text does not contain the feature and then extracted the
    record's exact value from it. Self-contradiction, automatically countable.
    """

    feature_key: str
    model_id: str
    hit_present: int
    hit_absent: int
    wrong_present: int
    wrong_absent: int
    missing_present: int
    missing_absent: int


@dataclass(frozen=True, slots=True)
class FlagInconsistencyRow:
    """`present = false`, yet the extracted value matched — per model.

    The one Goal 2 number that is a quality signal rather than a description,
    because it is a self-contradiction rather than a comparison against a gold
    label nobody has (§11.2).
    """

    model_id: str
    cell: Cell


@dataclass(frozen=True, slots=True)
class PerRecordRow:
    """One record where the column is populated and the narrative does not say so.

    **This list is the deliverable** — Goal 2 is consumed as a record list to
    act on, not as a rate (`design/results/README.md` §2e). `finding` is the
    plain sentence: "This report does not say what the weather was."

    `anonymised` is required wherever text is shown (`mvp-spec.md` §13's "the
    per-record anonymisation marking").
    """

    record_id: RecordId
    anonymised: bool
    record_value: str
    finding: str
    language: str
    language_confidence: float


@dataclass(frozen=True, slots=True)
class PresenceTabView:
    """Tab 2 — one model at a time, because presence is per-flag and a
    three-model grid would not be readable.

    Reports presence rate, the cross-tab and flag inconsistency, and
    **deliberately refuses presence precision / recall / F1** (`D2`): there is
    no independent gold label for presence, and deriving one from Goal 1
    correctness would be circular. The scope banner states that to the analyst
    verbatim and is not dismissible.
    """

    descriptor: RunDescriptorView
    models: tuple[ModelColumnView, ...]
    model_id: str
    rows: tuple[PresenceRow, ...]
    cross_tab: CrossTabView | None = None
    flag_inconsistency: tuple[FlagInconsistencyRow, ...] = ()
    records: Page[PerRecordRow] | None = None


@dataclass(frozen=True, slots=True)
class RankingRow:
    """One model's row of the ranking table.

    `rank` **repeats on a tie** (`1, 1, 3`), never enumerates (`1, 2, 3`):
    §11.5 renders overlapping intervals as a tie, not as an order.

    The last three fields are **reported, never scored** — the design's own
    rule 4, "the tie-breaker you apply, not one the tool applies". The presence
    rate joins them (`SD20`): §11.2 is unambiguous that presence has no gold
    label, and a model that flags everything present maximises it. None of the
    three takes any part in `rank`.
    """

    model_id: str
    tag: str
    digest: str
    rank: int
    macro_f1: float
    ci_low: float
    ci_high: float
    best: int
    tied: int
    worse: int
    verdict: str
    presence_rate: float
    median_latency_ms: int
    prompt_tokens: int
    vram_bytes: int


@dataclass(frozen=True, slots=True)
class SeparatingRow:
    """A feature where the two leaders' intervals do not overlap."""

    feature_id: FeatureId
    name: str
    source_label: str
    n: int
    #: Keyed by `model_id`, **in ranking order** when rendered.
    f1_by_model: Mapping[str, float]
    delta: float
    #: The plain sentence: "mistral leads alone — intervals clear by .020".
    reading: str


@dataclass(frozen=True, slots=True)
class RankingTabView:
    """Tab 3 — which model to pick, and where the evidence does not separate them.

    **Every number here is derived from tab 1's rows** through
    `domain/ranking.py`; nothing is stored and nothing is cached independently.
    If this and `ExtractionTabView` disagree, this one is wrong by construction
    (sw-design.md §16.5), which is what J13 asserts in the browser.

    An empty `separating` is a result, not a gap: it means this run does not
    separate the models, and the verdict says so.
    """

    descriptor: RunDescriptorView
    rows: tuple[RankingRow, ...]
    separating: tuple[SeparatingRow, ...]
    #: "Two models are tied at the top. This run does not separate them."
    #: Composed from the computed ranks, never authored.
    verdict_headline: str
    verdict_detail: str
    scored_feature_count: int
    unscored_feature_count: int


@dataclass(frozen=True, slots=True)
class ScoringStatusView:
    """Which of §16.7's three states a tab should render.

    Three states that must not share a rendering: **not scored yet**,
    **scoring…**, and **nothing scoreable** — and the third says *which*,
    because "no results" and "not enough data for results" are different facts
    about the run.
    """

    run_id: RunId
    scored_features: int
    labelled_features: int
    running: bool

    @property
    def is_scored(self) -> bool:
        return self.labelled_features > 0 and self.scored_features >= self.labelled_features

    @property
    def is_scoreable(self) -> bool:
        """`False` means there is nothing to score — every feature is
        exploratory. Distinct from "every feature is suppressed", which is
        scoreable and renders as suppression."""
        return self.labelled_features > 0


# ===========================================================================
# Reset and discard — sw-design.md §18
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DiscardPreviewView:
    """What a discard would destroy, counted before anything is destroyed.

    One shape for all three kinds, because the dialog is one dialog (§18.5)
    and a second shape is a second place for the copy to drift. A field that
    cannot apply to a kind is `0`, not `None`: "this delivery has no scores"
    and "nobody counted" are not different facts here.

    `active` is **G1 as a rendered state** rather than as an exception. The
    guard still raises on the action — the API owes a 409 either way — but a
    dialog has to be able to say "a run is still going" before the analyst
    presses anything, and a state the UI can only discover by provoking an
    error is not a state it can render (the same reasoning §15.5 applied to
    an unreachable endpoint).
    """

    kind: str
    """`run` · `evaluation` · `delivery`. A plain string: the routers and the
    dialog both key on it, and neither owns an enum the other would import."""
    target_id: str
    label: str
    """What the dialog's lead sentence names — "run 3 · qwen3:14b"."""
    runs: int
    extractions: int
    scores: int
    mismatches: int
    tagged_mismatches: int
    files: int
    """Delivery files that would be removed from disk. `0` for the other two."""
    active: bool
    """G1: this object holds a `queued` or `running` run."""
    active_detail: str | None = None
    """Which run, and in which status — so the refusal names the obstacle."""
    cited_by: int = 0
    """Corpora frozen from this delivery. Non-zero means the discard is
    refused outright (§18.2); there is no `force` for this one."""

    @property
    def has_exportable(self) -> bool:
        """The dialog's two states (§18.5): `False` renders "nothing to
        export" and enables Discard immediately."""
        return self.scores > 0 or self.mismatches > 0

    @property
    def blocked(self) -> bool:
        """Refused whatever the analyst does. `tagged_mismatches` is **not**
        here: that one warns and allows (R-D3)."""
        return self.active or self.cited_by > 0


@dataclass(frozen=True, slots=True)
class ScoreExportRow:
    """One `score` row on its way out of the database for good (§18.3)."""

    feature_key: str
    language: str
    metric: str
    value: float | None
    n: int
    ci_low: float | None
    ci_high: float | None


@dataclass(frozen=True, slots=True)
class MismatchExportRow:
    """One `mismatch`, **including the analyst's own columns**.

    `analyst_tag`, `tagged_at` and `note` are the only human-authored data in
    the pipeline, which is the whole reason this export exists (SD21, §18.3).
    """

    mismatch_id: str
    record_id: RecordId
    feature_key: str
    #: Nullable exactly as the column is: the corpus value is authoritative
    #: but a `wrong` outcome can be recorded against an absent one.
    record_value: str | None
    extracted_value: str | None
    evidence_span: str | None
    analyst_tag: str | None
    tagged_at: datetime | None
    note: str | None


@dataclass(frozen=True, slots=True)
class RunExportView:
    """A run's two exportable tables, read in one call before a discard."""

    run_id: RunId
    evaluation_id: EvaluationId
    model_tag: str
    scores: tuple[ScoreExportRow, ...]
    mismatches: tuple[MismatchExportRow, ...]


@dataclass(frozen=True, slots=True)
class DataDirView:
    """Which database the header chip names (§2.1 item 6).

    `ui/` may not import `ra2/infra/`, so the one `Settings` value the header
    shows arrives the way every other value does: through a service, as a read
    model.
    """

    data_dir: str
    database_path: str
