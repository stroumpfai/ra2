# STUB — bodies owned by L2 (feat/p3-evaluation-view, phase 3 Wave 4).
# Bodies landed on that branch; the M17 header line stays so
# `tests/test_p3_contract.py` keeps asserting the module it declared.
"""Evaluation view — "One corpus and one feature set, run across several models."

`design/prompt-evaluation/README.md` §2 (`Evaluation.dc.html`), implemented: a
setup column of six numbered steps beside a progress column of per-model cards,
the runs table and the reproducibility card.

The same three rules that shape `import_view.py` and `features_view.py` shape
every line here:

1. **The UI holds no business logic** (CLAUDE.md #7). Every count, status,
   fingerprint and feasibility judgement arrives from `EvaluationService` /
   `RunService` / `PromptService` as a detached read model. Notably
   `EvaluationView.can_launch` is *read*, never re-derived: whether an
   unreachable endpoint blocks Launch is a service's fact (plan-phase-3.md C3).
2. **No module-level mutable state** (CLAUDE.md #8). Which evaluation this tab
   is looking at, and the two picks that precede the evaluation row existing at
   all, live in `app.storage.client` through `ui/state.py`'s `EvaluationSetup`;
   the runs table's sort and page live there through `TableState`. Everything
   else is per-render local state on an `_EvaluationPage` built inside the page
   function, one per client.
3. **The UI calls services in-process as Python** (sw-design.md §1). There is
   no HTTP call to this app's own API anywhere in this file.

**Progress polling.** sw-design.md §9/§15.4 say "`GET /api/v1/tasks/{id}`
exposes progress; the UI polls it with `ui.timer`" — and `import_view.py`, the
pattern this file is told to copy, polls with `ui.timer` but reads the
**service**, not the endpoint. That is not a deviation from §9, it is what §9's
own rule ("the UI calls services in-process as Python, never over HTTP to its
own API") leaves once both are applied: `TaskProgress` is an `infra` type the
layer rule keeps out of `ui/`, and the honest source of "how far has this run
got" is `RunProgressView`, whose counts come from committed `extraction` rows
rather than from a task counter a restart can disagree with (§15 F6). So the
timer re-reads `EvaluationService.get()` and stops when no run is `queued` or
`running` — one polling loop, no websocket, no SSE.

**Four places this file departs from the drawn board, all deliberate:**

- *Step 2's note is not rendered at all.* The design reads "Freezes when the
  first run executes", which stopped being true at phase 2 — `mvp-spec.md` §9
  says a feature set is **already frozen from the moment it was created**, and
  an evaluation only ever cites an already-frozen config. Phase 3 rendered a
  corrected sentence in its place (C5 / R6); it is now dropped, with the
  correction kept here. The statement never stopped being true, it stopped
  being *new* on the twentieth viewing, and the setup column is six steps deep
  in a 430px column where every line of explanation pushes Launch further
  down. What made it load-bearing is enforced where it belongs: `launch`
  refuses an unfrozen config (`EVAL_ERROR_CONFIG_NOT_FROZEN`). The reason the
  design's own sentence was wrong stays written down here, because that is the
  argument against reinstating it from the mock
  (`plan-evaluation-view-improvements.md` §3).
- *The token figure* in the prompt preview is `≈ N tokens` — an estimate, and
  labelled as one, because an exact count needs the model's tokeniser and
  every tokeniser package downloads its vocabulary (N1, C6, R8).
- *The reproducibility card carries no explainer.* Phase 3 put a paragraph
  under the provenance line explaining why a prompt template is versioned
  separately. Dropped for step 2's reason, and with less cost: the card still
  *renders* the template version and its fingerprint, which is the fact the
  paragraph was talking about.
- *The toolbar's right group* carries **"New evaluation"** wherever "Save
  draft" cannot honestly act, and the setup column carries `LAUNCHED_MESSAGE`
  once it is locked (`sw-design.md` §13 `SD32`). The design's fixture shows an
  evaluation that already exists, so it draws neither; without them a launched
  evaluation is a dead end with nothing on screen saying why, and the "clone
  into a new evaluation" its own step-2 copy prescribes has nowhere to go.

**Three components this view places but does not implement** —
`progress_card`, `ollama_settings_dialog` and `prompt_preview_panel` — are
L3's, built in parallel this wave against the signatures frozen at M17
(plan-phase-3.md §3.1). This file passes each one its read model and reaches
inside none of them; the settings dialog brings its own `ui.dialog()`, so the
view keeps only the handle it needs to close it on "refresh".

**Judgment calls made here, and why:**

- *Every step persists as it is chosen.* Steps 1-6 are discrete choices, and
  `EvaluationView.can_launch` — which this view is told to read rather than
  re-derive — is computed from the **persisted** `selected_models`. A local
  edit buffer would make the Launch button disagree with the service about its
  own precondition, so there is none; `update_draft` is called as each control
  changes. "Save draft" therefore only ever *re-saves* an existing draft, which
  is the one thing it can honestly mean once everything else already saves
  itself — creating is `NEW_EVALUATION_LABEL`'s, and the two are never on
  screen together.
- *The temperature ladder* (`TEMPERATURE_CHOICES`) is this view's own: the
  design draws a caret and one fixed value, so the option list is
  underspecified in exactly the way `census_view.POPULATED_THRESHOLDS` and
  `features_view.STATE_OPTIONS` were, and it is resolved the same way — the
  smallest ladder that answers the question, named here rather than invented
  at the call site.
- *A new evaluation's name* is the cited feature set's. The design has no name
  control and `save_draft` requires one; naming the draft after what it pins
  is the only choice that carries information.
- *The Run column links to `/results`*, which is a placeholder route this
  phase. A link that lands on "Not built in phase 1" is honest; hiding the
  link would be the design's affordance quietly missing.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Final, cast

from nicegui import ui
from nicegui.element import Element

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.llm import REASONING_EFFORTS, EndpointStatus
from ra2.services.container import Services
from ra2.services.errors import ServiceError
from ra2.services.readmodels import (
    ConnectionProbeView,
    ConnectionView,
    CorpusView,
    EvaluationView,
    FeatureSetSummary,
    ModelChoiceView,
    Page,
    PromptTemplateView,
    ProvenanceView,
    RunExportView,
    RunProgressView,
    RunView,
    SortDir,
)
from ra2.ui.components import (
    ColumnSpec,
    card,
    card_header,
    data_table,
    dialog_card,
    format_count,
    format_local,
    icon_button,
    pagination_row,
    tick,
)
from ra2.ui.components.discard_dialog import discard_dialog
from ra2.ui.components.ollama_settings import ollama_settings_dialog
from ra2.ui.components.primitives import (
    data_props,
    labeled_field,
    master_detail_split,
    pill,
    radio_option,
    scroll_well,
    step_label,
)
from ra2.ui.components.progress_card import progress_card
from ra2.ui.components.prompt_preview import prompt_preview_panel
from ra2.ui.shell import NAV_ITEMS, shell
from ra2.ui.state import (
    EvaluationSetup,
    TableState,
    evaluation_setup,
    set_evaluation_setup,
    set_table_state,
    table_state,
)

__all__ = [
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "DETERMINISM_NOTE",
    "DEV_MARKER",
    "DISCARD_EVALUATION_LABEL",
    "ENDPOINT_WORDS",
    "LAUNCHED_MESSAGE",
    "MODELS_UNSAVED_MESSAGE",
    "MODELS_WELL_PX",
    "NEW_EVALUATION_LABEL",
    "NO_RUNS_MESSAGE",
    "NO_SETUP_MESSAGE",
    "PAGE_SIZE",
    "PINNED_SUFFIX",
    "POLL_FAST_S",
    "POLL_FAST_TICKS",
    "POLL_SETTLED_S",
    "PROGRESS_CAPTION",
    "PROGRESS_TITLE_SETTLED",
    "PROMPT_NOTE",
    "PROVENANCE_TITLE",
    "REASONING_LABEL",
    "RESULTS_LINK_LABEL",
    "RUNS_TABLE",
    "RUNS_TITLE",
    "SCORED_MARKER",
    "SETUP_LIST_EXTRA",
    "SIZE_NOTE",
    "STATUS_COLUMN_PX",
    "STEP_TITLES",
    "TEMPERATURE_CHOICES",
    "TIMESTAMP_FORMAT",
    "UNSAVED_MESSAGE",
    "register",
]

_ITEM = next(i for i in NAV_ITEMS if i.key == "evaluation")

#: Edge-to-edge: the toolbar and the two split columns each carry their own
#: padding (README §2, "Layout"), exactly as the Features view does.
CONTENT_PADDING = "0"
CONTENT_GAP = "0"

#: One namespace for this tab's runs table, so its page never collides with
#: another view's.
RUNS_TABLE: Final = "evaluation.runs"
#: README §2, "Runs table": "Paginated at **10 rows**".
PAGE_SIZE: Final = 10
#: Enough to exhaust one evaluation's runs in a single round trip, for the
#: card header's "N · M dev · K failed" summary — the same bound and the same
#: reasoning as `features_view.CORPUS_CHOICES`.
RUNS_SUMMARY_CAP: Final = 500

#: README §2, "Fixed sizes that matter here": models well 196px = 4 rows.
MODELS_WELL_PX: Final = 196
#: README §2, "Runs table": four columns at the design's widths, plus a Status
#: column this implementation widens — `STATUS_COLUMN_PX` says why. The well is
#: `overflow:auto`, so the table scrolls horizontally rather than collapsing a
#: column below the width its contents need; that is the README's own stated
#: purpose for the well, and it is what makes the widening affordable.
RUNS_TABLE_MIN_WIDTH_PX: Final = 74 + 132 + 66 + 152 + 200

#: The Status column. **200px, against the design's 84.**
#:
#: 84px is the right width for what the design draws in this cell: one state
#: word. It is not what the cell holds. Phase 5 put `discard` here rather than
#: in a sixth column precisely to keep the five drawn widths (CONTRACTS.md,
#: `feat-reset-discard-*`), and `interrupted` runs already carried `Resume`
#: beside it; Stage 1 of `plan-fix-evaluation-runs.md` added `log`, and Stage 2
#: adds the `DEV` chip. Five things in a cell sized for one.
#:
#: Keeping 84px did not make them fit — `table-layout:fixed` does not clip, so
#: they simply drew over the neighbouring column. That trade preserved the
#: number in the README and sacrificed the thing the number was for. Clipping
#: is not available here either: three of the five are buttons, and a control
#: hidden under `overflow:hidden` is one nobody can press — the defect
#: `theme.py`'s own `.td-clip` note was written about.
#:
#: So the width follows the contents: "interrupted" + `DEV` + Resume + log +
#: discard, at this cell's 11px/10.5px mono and 6px gaps, is a little under
#: 200px. The other four columns keep the design's widths exactly and are
#: clipped with `.td-clip`, because all four hold text.
STATUS_COLUMN_PX: Final = "200px"

#: README §2, "Layout". Both numbers were regressions at some point and both
#: are asserted: `align-self:flex-start` (without it the `margin-top:auto`
#: launch row is pushed to the bottom of a stretched column, leaving a ~530px
#: gap) and the 320px floor the split shrinks to instead of wrapping.
SETUP_LIST_EXTRA: Final = (
    "flex:0 1 430px;min-width:320px;align-self:flex-start;"
    "padding:16px 20px 20px;gap:14px;overflow:hidden;"
)
PROGRESS_DETAIL_EXTRA: Final = (
    "flex:1 1 520px;min-width:360px;padding:16px 28px 20px;"
    "display:flex;flex-direction:column;gap:12px;overflow:auto;"
)

TOOLBAR_STYLE: Final = (
    "display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:11px 28px;"
    "background:var(--surface);border-bottom:1px solid var(--rule);flex:none;"
)
LEFT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;"
#: README §2, "Toolbar": `margin-left:auto` on the group, **not** a `flex:1`
#: spacer — the spacer breaks right alignment when the row wraps.
RIGHT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;margin-left:auto;flex:none;"

#: The design's `.sel`: a full-width select, mono 11.5px. `.rof` is the same
#: box at the Features view's sans 12.5px, so only the type is repointed.
SEL_STYLE: Final = "font-family:var(--mono);font-size:11.5px;"
STEP_STYLE: Final = "display:flex;flex-direction:column;min-width:0;"
NOTE_STYLE: Final = "font-size:11.5px;line-height:1.5;margin-top:6px;"

#: The gear that opens Ollama connection settings (README §2 step 4). Lucide's
#: `settings` shape, defined here rather than in `components/icons.py`: that
#: file is M17's and frozen to this wave (plan-phase-3.md §6).
GEAR: Final = (
    '<circle cx="12" cy="12" r="3"></circle>'
    '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 '
    "1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 "
    "19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 "
    "15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 "
    "0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 "
    "1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 "
    "2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 "
    '0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>'
)

# --- copy, from design/prompt-evaluation/README.md §2 -----------------------

#: The toolbar's pinned-inputs line: `EvaluationView.feature_config_label`
#: followed by this. "Weather & conditions · v2 — only the model varies".
PINNED_SUFFIX: Final = " — only the model varies"
SAVE_DRAFT_LABEL: Final = "Save draft"
#: The creation affordance the design never drew, in `features_view`'s "New
#: set" and `prompts_view`'s "New version" register (SD32). It is the **only**
#: toolbar button in the two states where "Save draft" cannot honestly act:
#: before any evaluation exists, and after one has been launched.
NEW_EVALUATION_LABEL: Final = "New evaluation"
#: The evaluation-level discard, in the runs card's header control slot rather
#: than in the toolbar (`SD35`). It says "evaluation" out loud because the rows
#: under it each carry a bare "discard" that takes one run.
DISCARD_EVALUATION_LABEL: Final = "Discard evaluation"

STEP_TITLES: Final[tuple[str, ...]] = (
    "Corpus",
    "Feature set",
    "Prompt",
    "Models",
    "Determinism",
    "Size",
)

PROMPT_NOTE: Final = (
    "The wording around the feature descriptions. Travels in the run's fingerprint."
)
DETERMINISM_NOTE: Final = (
    "Temperature 0.0 takes the most likely token every time; the seed fixes what "
    "remains random. Same inputs, same output — a re-run is a check, not a new sample. "
    "Reasoning above “none” lets the model think before it answers: better on some "
    "features, and tens of times slower per record."
)
#: Step 5's third control. The four values are the endpoint's vocabulary
#: (`domain.llm.REASONING_EFFORTS`), **not** a ladder this view invented the
#: way `TEMPERATURE_CHOICES` is: what Ollama maps is a fact about the endpoint,
#: and `EvaluationService` refuses anything outside it.
REASONING_LABEL: Final = "Reasoning"
#: The design names the literal 200 (`RA2_EVAL_RECORD_MIN`). No read model
#: carries it and `ui/` may not import `infra`, so the sentence keeps its
#: meaning and drops the number rather than hard-coding a setting (CLAUDE.md
#: #7 — every number comes from a service).
SIZE_NOTE: Final = (
    "Below the evaluation minimum a run is marked dev and every view carries "
    "“smoke test, not a result”."
)
#: The design's own header for this column (`design/prompt-evaluation/README.md`
#: §2), and it is **kept verbatim for the state the design drew** — a run in
#: flight. It was rendered in every other state too, which is how a column of
#: cards all reading `done` sat under the words "In progress" and was read,
#: reasonably, as a screen that had not moved. The design mock shows this
#: column mid-run and says nothing about the rest, so the settled wording
#: below is this view's own answer rather than a departure from the design.
PROGRESS_TITLE: Final = "In progress"
PROGRESS_TITLE_SETTLED: Final = "Runs"
#: What a finished, scored card offers: the one link the analyst has been
#: waiting for. Without it the Evaluation screen never says the boards exist,
#: and the only route to them is a runs-table link two cards further down.
RESULTS_LINK_LABEL: Final = "See results"
SCORED_MARKER: Final = "scored"
PROGRESS_CAPTION: Final = (
    "in-process asyncio worker · restart-safe · resumes from last committed extraction"
)
RUNS_TITLE: Final = "Runs in this evaluation"
PROVENANCE_TITLE: Final = "Stored on every run — enough to reproduce it"
PREVIEW_LABEL: Final = "Preview prompt"

#: README §2, "Runs table": `dd.mm.yy - hh:mm:ss`, on one line.
TIMESTAMP_FORMAT: Final = "%d.%m.%y - %H:%M:%S"

#: This view's own ladder for an underspecified control (module docstring).
TEMPERATURE_CHOICES: Final[tuple[float, ...]] = (0.0, 0.2, 0.5, 0.7, 1.0)

#: The progress poll's two intervals, and how long the first one lasts.
#:
#: 0.2 s is `import_view`'s, and right for what this shares with Import: the
#: seconds just after a submit, where the worker's first write is imminent and
#: a stale screen is most misleading. It is wrong for everything after that. A
#: run is minutes per record at best and hours end to end, so holding 0.2 s
#: means six hundred full re-reads and redraws between two numbers changing —
#: against a SQLite file the worker is also committing to.
#:
#: `POLL_FAST_TICKS` × `POLL_FAST_S` is three seconds of handshake before the
#: ladder drops. Neither value is a setting: an analyst has no basis on which
#: to turn either, and the thing they would be tuning is a redraw rate.
POLL_FAST_S: Final = 0.2
POLL_SETTLED_S: Final = 2.0
POLL_FAST_TICKS: Final = 15

#: The design's dev-sized marker (README §2), now a chip **beside** the status
#: word rather than in place of it — `_status_marker` has the reasoning.
DEV_MARKER: Final = "DEV"

#: One rendering table for the endpoint line's state word, keyed on the
#: service's enum — the `FindingCode` discipline (CLAUDE.md, "Findings, not
#: prose"): the code is the stable identifier, the wording lives in `ui/`.
ENDPOINT_WORDS: Final[dict[EndpointStatus, str]] = {
    EndpointStatus.REACHABLE: "reachable",
    EndpointStatus.UNREACHABLE: "unreachable",
    EndpointStatus.TIMED_OUT: "timed out",
    EndpointStatus.REFUSED_NOT_LOOPBACK: "refused — not loopback",
}

#: Undesigned states, in the tone README's "Loading / empty / error" section
#: asks for and plan-phase-3.md C3 settles: the standard empty card, no new
#: pattern.
NO_SETUP_MESSAGE: Final = (
    "No evaluation yet — pick a corpus and a frozen feature set, then “New evaluation”."
)
NO_CORPUS_MESSAGE: Final = "No corpus yet — freeze one on Import first."
NO_FROZEN_SET_MESSAGE: Final = "No frozen feature set yet — create one on Features first."
NO_TEMPLATE_MESSAGE: Final = "No prompt template yet — save one on Prompts first."
#: The endpoint answered, and has nothing. Names the fix: a reachable
#: Ollama with no model pulled is a completely ordinary state on a fresh
#: install, and "empty catalogue" alone does not tell you what to do.
NO_MODELS_MESSAGE: Final = "No models — the endpoint has none. Pull one with “ollama pull”."
#: The endpoint was never answered for, so there is no catalogue to call
#: empty. Which refusal it was — unreachable, or not loopback — is on the
#: reason line under the card, so it is not repeated here.
NO_MODELS_UNREACHABLE_MESSAGE: Final = "No models — the endpoint could not be asked."
NO_RECORDS_MESSAGE: Final = "This corpus has no records to preview a prompt against."
NO_RUNS_MESSAGE: Final = "No runs yet — Launch queues one per selected model."
NO_PROVENANCE_MESSAGE: Final = "Nothing stored yet — provenance is written when a run starts."
UNSAVED_MESSAGE: Final = "“New evaluation” pins the prompt, the decoding settings and the size."
#: Step 4's own version of `UNSAVED_MESSAGE`: the list above is real and
#: current, and only the selection needs somewhere to be recorded.
MODELS_UNSAVED_MESSAGE: Final = "“New evaluation” first — the ticks need a row to record into."
DRAFT_SAVED_MESSAGE: Final = "Draft saved."
EVALUATION_CREATED_MESSAGE: Final = "New evaluation created."
#: After the row is gone. Named, because with no switcher the screen is about
#: to show a *different* evaluation and the analyst is owed the reason.
EVALUATION_DISCARDED_MESSAGE: Final = "Discarded evaluation {name}."
#: Why the setup column is read-only, and the way out. Rendered **over the
#: whole column**, not beside step 4: the lock is not step 4's, and three of
#: its neighbours were equally silent about it (SD32).
LAUNCHED_MESSAGE: Final = (
    "Launched — every step below is fixed, because the runs beside them cite these "
    "exact inputs. “New evaluation” clones the corpus and the feature set into an "
    "editable draft."
)
UNKNOWN_VALUE: Final = "unknown"
EMPTY_CELL: Final = "—"


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _EvaluationPage(services)
        await page.build()


class _EvaluationPage:
    """One client's Evaluation view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (CLAUDE.md #8). It holds only what it
    last read from a service; it is never the source of truth for any of it.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._view: EvaluationView | None = None
        self._corpora: tuple[CorpusView, ...] = ()
        self._sets: tuple[FeatureSetSummary, ...] = ()
        self._templates: tuple[PromptTemplateView, ...] = ()
        self._runs: Page[RunView] | None = None
        self._all_runs: tuple[RunView, ...] = ()
        #: Which runs of this evaluation have scores, so a finished card can
        #: carry the link the analyst is waiting for. Read from
        #: `ResultsService.scoring_status`, never derived here.
        self._scored_runs: frozenset[RunId] = frozenset()
        self._connection: ConnectionView | None = None
        #: The endpoint's catalogue. Held separately from `_view`
        #: because it does not depend on one: which models the endpoint
        #: offers is the endpoint's fact, and only the ticks are the
        #: evaluation's. Reaching it through `_view` is what left the
        #: Models card empty on every database with no evaluation yet.
        self._models: tuple[ModelChoiceView, ...] = ()
        self._root: Element | None = None
        self._toolbar: Element | None = None
        self._setup_slot: Element | None = None
        self._progress_slot: Element | None = None
        self._poll: ui.timer | None = None
        #: The open settings dialog, so "refresh" can close it.
        self._settings_dialog: ui.dialog | None = None

    # --- lifecycle -----------------------------------------------------------

    async def build(self) -> None:
        data_dir_view = self._services.lifecycle.data_dir()
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            data_dir=data_dir_view.data_dir,
            database_replaced=data_dir_view.database_replaced,
            content_padding=CONTENT_PADDING,
            content_gap=CONTENT_GAP,
        ):
            self._root = ui.element("div").style(
                "display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;"
            )
            with self._root:
                self._toolbar = (
                    ui.element("div").props('data-testid="evaluation-toolbar"').style(TOOLBAR_STYLE)
                )
                self._setup_slot, self._progress_slot = master_detail_split(
                    list_extra=SETUP_LIST_EXTRA, detail_extra=PROGRESS_DETAIL_EXTRA
                )
        await self.reload()
        # A run already in flight when this page opens must tick too. Polling
        # used to start only from Launch and Resume, so the tab that submitted
        # the work updated and every other view of it did not: reload the
        # browser mid-run, or open the page in a second tab, and the screen
        # froze at whatever it read once — indistinguishable from a worker
        # that had died, which is the confusion this whole branch is about.
        # `_start_polling` is a no-op when there is already a timer, and the
        # timer stops itself on the first settled tick, so this costs one read
        # on a page with nothing running.
        if not self._settled:
            self._start_polling()

    async def reload(self) -> None:
        """Re-read everything this view shows, then redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated — `import_view.reload`'s shape, and its reason
        for running the body inside `_root` rather than inside whichever
        element fired the event: `_root` is built once and never cleared, so
        it outlives every redraw and every button in it.
        """
        assert self._root is not None  # built in `build()`, before any reload
        with self._root:
            self._corpora = (
                await self._services.corpus.list_corpora(
                    sort_key="imported_at",
                    sort_dir=SortDir.DESC,
                    page=1,
                    page_size=RUNS_SUMMARY_CAP,
                )
            ).items
            self._sets = tuple(
                s for s in await self._services.feature.list_configs() if s.is_frozen
            )
            self._templates = tuple(await self._services.prompt.list_versions())
            self._view = await self._current_evaluation()
            if self._view is None:
                # `catalogue()` rather than `connection_status()`: the card can
                # list what the endpoint offers long before an evaluation row
                # exists, and one call fetches both facts.
                catalogue = await self._services.evaluation.catalogue()
                self._connection = catalogue.connection
                self._models = catalogue.models
                self._runs = None
                self._all_runs = ()
            else:
                self._connection = self._view.connection
                self._models = self._view.models
                evaluation_id = self._view.draft.evaluation_id
                state = table_state(
                    RUNS_TABLE, sort_key="started_at", sort_dir=SortDir.DESC, page_size=PAGE_SIZE
                )
                self._runs = await self._services.run.list_runs(
                    evaluation_id,
                    page=state.page,
                    page_size=state.page_size,
                    sort_key=state.sort_key,
                    sort_dir=state.sort_dir,
                )
                self._all_runs = (
                    await self._services.run.list_runs(
                        evaluation_id, page=1, page_size=RUNS_SUMMARY_CAP
                    )
                ).items
                self._scored_runs = await self._read_scored(evaluation_id)
            self._render()

    async def refresh_progress(self) -> None:
        """Re-read only what a run in flight changes, and redraw only that
        column. **This is what the timer calls**; `reload` is what a view load
        and a user action call.

        The split exists because `reload` probes the endpoint. It reads
        `evaluation.get()`, which reads `connection_status()` and
        `_model_choices()`, and both reach `/api/tags` — so a timer at 0.2 s
        put **ten HTTP requests a second on the endpoint the worker was
        waiting on**, and a `pynvml` probe five times a second beside them,
        for the whole length of a run. `connection_status`' own docstring
        forbids this in as many words: "re-checked on view load and when the
        settings dialog's refresh is pressed — **never on a timer**"
        (plan-phase-3.md C3).

        So the endpoint state this view already holds is handed back to
        `get()` rather than re-asked for, and the corpora, feature sets and
        templates are not re-read at all: a run in flight cannot change any of
        them. What is left is the progress cards, the runs table and the
        provenance line — all of them counts over committed rows.
        """
        if self._view is None or self._connection is None or self._progress_slot is None:
            # Nothing has been loaded yet, so there is no cheap refresh to do
            # and nothing to hand back. A full read is the honest fallback.
            await self.reload()
            return
        evaluation_id = self._view.draft.evaluation_id
        self._view = await self._services.evaluation.get(
            evaluation_id, connection=self._connection, models=self._models
        )
        state = table_state(
            RUNS_TABLE, sort_key="started_at", sort_dir=SortDir.DESC, page_size=PAGE_SIZE
        )
        self._runs = await self._services.run.list_runs(
            evaluation_id,
            page=state.page,
            page_size=state.page_size,
            sort_key=state.sort_key,
            sort_dir=state.sort_dir,
        )
        self._all_runs = (
            await self._services.run.list_runs(evaluation_id, page=1, page_size=RUNS_SUMMARY_CAP)
        ).items
        self._scored_runs = await self._read_scored(evaluation_id)
        self._progress_slot.clear()
        with self._progress_slot:
            self._render_progress()

    async def _read_scored(self, evaluation_id: EvaluationId) -> frozenset[RunId]:
        """Which of this evaluation's runs have a board to link to.

        A read, not a derivation: `ScoringStatusView.is_scored` is the same
        property the Results view branches on, so the link on the card and
        the page it opens cannot disagree about whether there is anything
        there. Counted over committed `score` rows, like everything else
        about scoring (§16.1, F5).
        """
        statuses = await self._services.results.scoring_status(evaluation_id)
        return frozenset(status.run_id for status in statuses if status.is_scored)

    async def _current_evaluation(self) -> EvaluationView | None:
        """The evaluation this tab is looking at.

        The design shows exactly one evaluation and has no switcher. This picks
        the one remembered per client — so a redraw cannot silently move the
        analyst to a different one — falling back to the newest that exists, in
        `import_view._current_delivery`'s shape and for its reason.
        """
        setup = evaluation_setup()
        drafts = await self._services.evaluation.list_evaluations()
        if not drafts:
            set_evaluation_setup(EvaluationSetup())
            return None
        remembered = next((d for d in drafts if str(d.evaluation_id) == setup.evaluation_id), None)
        chosen = remembered if remembered is not None else drafts[0]
        set_evaluation_setup(
            EvaluationSetup(
                evaluation_id=str(chosen.evaluation_id),
                corpus_id=str(chosen.corpus_id),
                feature_config_id=str(chosen.feature_config_id),
            )
        )
        return await self._services.evaluation.get(chosen.evaluation_id)

    # --- rendering -----------------------------------------------------------

    def _render(self) -> None:
        # Both are built in `build()`, before anything can render.
        assert self._toolbar is not None
        assert self._setup_slot is not None
        assert self._progress_slot is not None
        self._toolbar.clear()
        with self._toolbar:
            self._render_toolbar()
        self._setup_slot.clear()
        with self._setup_slot:
            self._render_setup()
        self._progress_slot.clear()
        with self._progress_slot:
            self._render_progress()

    # --- toolbar -------------------------------------------------------------

    def _render_toolbar(self) -> None:
        view = self._view
        with ui.element("div").style(LEFT_GROUP_STYLE):
            label = "" if view is None else view.feature_config_label
            ui.label(f"{label}{PINNED_SUFFIX}" if label else NO_SETUP_MESSAGE).classes(
                "mono ink2"
            ).props('data-testid="pinned-inputs"').mark("pinned-inputs").style("font-size:11px;")
        with ui.element("div").style(RIGHT_GROUP_STYLE):
            if self._can_save_draft():
                self._toolbar_button(
                    SAVE_DRAFT_LABEL,
                    testid="save-draft",
                    enabled=True,
                    on_click=self._save_draft,
                )
            else:
                self._toolbar_button(
                    NEW_EVALUATION_LABEL,
                    testid="new-evaluation",
                    enabled=self._can_create(),
                    on_click=self._new_evaluation,
                )

    def _toolbar_button(
        self,
        label: str,
        *,
        testid: str,
        enabled: bool,
        on_click: Callable[[], Awaitable[None]],
    ) -> None:
        button = (
            ui.element("button")
            .classes("btn secondary")
            .props(f'type="button" data-testid="{testid}"')
            .mark(testid)
        )
        if enabled:
            button.on("click", _sync(on_click))
        else:
            button.props("disabled").style("opacity:.45;")
        with button:
            ui.label(label)

    def _can_save_draft(self) -> bool:
        """Whether the toolbar's one button is "Save draft" rather than "New
        evaluation" — **the two are mutually exclusive** (SD32).

        There is exactly one thing to offer in each of the three states, and
        the label never has to describe an act the press cannot perform: with
        no evaluation there is nothing to save, after a launch there is
        nothing left to edit, and on an unlaunched draft a *second* draft
        would be debris — the one on screen is already fully editable, and
        this view has no switcher to find the other one with again.
        """
        view = self._view
        return view is not None and not view.draft.is_launched

    def _can_create(self) -> bool:
        """ "New evaluation" cites a corpus and a **frozen** feature set, so
        both have to exist. Steps 1 and 2 already say which one is missing."""
        return bool(self._corpora) and bool(self._sets)

    # --- setup column --------------------------------------------------------

    def _render_setup(self) -> None:
        if self._locked:
            self._launched_note()
        self._step_corpus()
        self._step_feature_set()
        self._step_prompt()
        self._step_models()
        self._step_determinism()
        self._step_size()
        self._launch_row()

    def _launched_note(self) -> None:
        """The reason the six steps below are read-only.

        It sits at the head of the **column**, not inside a step: every
        control in it is locked by the same fact, and hanging the sentence
        off step 4 would say so about one of them and leave the other five
        silent. Before this existed the column said nothing at all — the
        selects were simply dead (SD32).
        """
        ui.label(LAUNCHED_MESSAGE).classes("warn").props('data-testid="launched-note"').mark(
            "launched-note"
        ).style("font-size:11.5px;line-height:1.5;")

    def _step(self, number: int, *, extra: str = "") -> Element:
        element = (
            ui.element("div")
            .props(f'data-testid="step-{number}"')
            .mark(f"step-{number}")
            .style(f"{STEP_STYLE}{extra}")
        )
        with element:
            step_label(number, STEP_TITLES[number - 1])
        return element

    @property
    def _locked(self) -> bool:
        """Every setup control is read-only once the evaluation is launched
        (sw-design.md §15.2: editable while `launched_at IS NULL`)."""
        return self._view is not None and self._view.draft.is_launched

    def _step_corpus(self) -> None:
        with self._step(1):
            if not self._corpora:
                _empty_line(NO_CORPUS_MESSAGE)
                return
            current = self._selected_corpus_id()
            _select(
                options=[(str(c.corpus_id), _corpus_label(c)) for c in self._corpora],
                value=current or "",
                label="Corpus",
                on_change=_sync(self._pick_corpus),
                testid="corpus-select",
                disabled=self._locked,
            )

    def _step_feature_set(self) -> None:
        with self._step(2):
            if not self._sets:
                _empty_line(NO_FROZEN_SET_MESSAGE)
                return
            current = self._selected_config_id()
            _select(
                options=[(str(s.feature_config_id), _set_label(s)) for s in self._sets],
                value=current or "",
                label="Feature set",
                on_change=_sync(self._pick_feature_set),
                testid="feature-set-select",
                disabled=self._locked,
            )

    def _step_prompt(self) -> None:
        with self._step(3):
            view = self._view
            if view is None:
                _empty_line(UNSAVED_MESSAGE)
                return
            if not self._templates:
                _empty_line(NO_TEMPLATE_MESSAGE)
                return
            current = view.draft.prompt_template_id
            with ui.element("div").style("display:flex;align-items:center;gap:8px;min-width:0;"):
                _select(
                    options=[
                        (str(t.prompt_template_id), f"template · v{t.version}")
                        for t in self._templates
                    ],
                    value="" if current is None else str(current),
                    label="Prompt template",
                    on_change=_sync(self._pick_template),
                    testid="prompt-select",
                    disabled=self._locked,
                )
                active = next((t for t in self._templates if t.is_active), None)
                if active is not None and active.prompt_template_id == current:
                    pill("active", tone="ok")
            ui.label(PROMPT_NOTE).classes("ink2").props('data-testid="prompt-note"').mark(
                "prompt-note"
            ).style(NOTE_STYLE)

    def _step_models(self) -> None:
        """The catalogue, whether or not an evaluation exists.

        It used to read `() if view is None else view.models`, which made the
        card dead on every database without an evaluation — the state a fresh
        install is in, and the one where "is Ollama set up?" is the actual
        question. The list comes from `_models` now; only the **ticks** need
        an evaluation to record into, so only they are withheld.
        """
        models = self._models
        with self._step(4):
            with card():
                with scroll_well(max_height_px=MODELS_WELL_PX):
                    if not models:
                        _empty_line(self._no_models_message())
                    for choice in models:
                        self._model_row(choice)
                self._models_footer(models)
            if models and self._view is None:
                _empty_line(MODELS_UNSAVED_MESSAGE)
            self._endpoint_line()

    def _no_models_message(self) -> str:
        """Why the list is empty, not one sentence for three different causes.

        The old wording said "the endpoint returned an empty catalogue" no
        matter what — including when the endpoint was never asked, which was
        exactly the case that made this look like a refresh bug. An endpoint
        that could not be answered for gets its own line, and the reason
        underneath the card already names which of the two refusals it was.
        """
        connection = self._connection
        if connection is not None and not connection.is_reachable:
            return NO_MODELS_UNREACHABLE_MESSAGE
        return NO_MODELS_MESSAGE

    def _model_row(self, choice: ModelChoiceView) -> None:
        """README §2 step 4: a 13×13 tick, the mono tag over a mono `--ink3`
        "digest … · size" line. A model the host is **known** not to have the
        VRAM for is `opacity:.55` with its size line in `--warn`."""
        # A tick writes into `evaluation.selected_models_json`, so there has
        # to be an evaluation to write into. `_toggle_model` already returns
        # early without one; this is what stops the tick looking live while
        # silently swallowing the click.
        disabled = choice.disabled or self._locked or self._view is None
        with data_props(
            ui.element("div")
            .props(
                f'data-testid="model-row" data-disabled="{"true" if choice.disabled else "false"}"'
            )
            .mark("model-row", f"model-{choice.tag}")
            .style(
                "display:flex;align-items:center;gap:10px;padding:8px 12px;"
                "border-bottom:1px solid var(--rule2);min-width:0;"
                + ("opacity:.55;" if choice.disabled else "")
            ),
            {"data-model": choice.tag},
        ):
            tick(
                checked=choice.selected,
                label=f"Select {choice.tag}",
                disabled=disabled,
                on_change=None if disabled else _toggle(self._toggle_model, choice.tag),
            )
            with ui.element("div").style("display:flex;flex-direction:column;min-width:0;"):
                ui.label(choice.tag).classes("mono").props('data-testid="model-tag"').mark(
                    "model-tag"
                ).style("font-size:12px;overflow:hidden;text-overflow:ellipsis;")
                ui.label(self._size_line(choice)).classes(
                    "mono warn" if choice.disabled else "mono ink3"
                ).props('data-testid="model-size"').mark("model-size").style("font-size:10.5px;")

    def _size_line(self, choice: ModelChoiceView) -> str:
        """ "digest 8fa1c3d0 · 8.5 GB", or the design's refusal line
        "42.5 GB — exceeds 24 GB VRAM" when the host is known not to fit it.

        Byte-to-gigabyte formatting only — `fits_vram` is the service's
        judgement (sw-design.md §15.6), never re-derived here.
        """
        size = _gigabytes(choice.size_bytes)
        if not choice.disabled:
            return f"digest {choice.digest} · {size}"
        vram = self._connection.gpu_vram_bytes if self._connection is not None else None
        limit = UNKNOWN_VALUE if vram is None else _gigabytes(vram)
        return f"{size} — exceeds {limit} VRAM"

    def _models_footer(self, models: Sequence[ModelChoiceView]) -> None:
        selected = sum(1 for m in models if m.selected)
        with (
            ui.element("div")
            .props('data-testid="models-footer"')
            .style(
                "display:flex;align-items:center;justify-content:space-between;gap:8px;"
                "padding:8px 12px;border-top:1px solid var(--rule);flex:none;min-width:0;"
            )
        ):
            ui.label(f"{len(models)} available · {selected} selected").classes("mono ink3").props(
                'data-testid="models-count"'
            ).mark("models-count").style("font-size:10.5px;overflow:hidden;text-overflow:ellipsis;")
            icon_button(
                GEAR,
                label="Ollama connection settings",
                size=24,
                glyph=13,
                stroke=1.8,
                on_click=_sync(self._open_settings),
            )

    def _endpoint_line(self) -> None:
        """The endpoint line, **below** the card, carrying the unreachable
        reason beside it rather than as a toast (plan-phase-3.md C3)."""
        connection = self._connection
        if connection is None:
            return
        word = ENDPOINT_WORDS[connection.status]
        with ui.element("div").style("margin-top:6px;display:flex;flex-direction:column;gap:3px;"):
            ui.label(f"endpoint {_endpoint_text(connection.endpoint)} · {word}").classes(
                "mono ink3"
            ).props('data-testid="endpoint-line"').mark("endpoint-line").style("font-size:10.5px;")
            if connection.reason is not None:
                ui.label(connection.reason).classes("danger").props(
                    'data-testid="endpoint-reason"'
                ).mark("endpoint-reason").style("font-size:11.5px;line-height:1.45;")

    def _step_determinism(self) -> None:
        view = self._view
        with self._step(5):
            if view is None:
                _empty_line(UNSAVED_MESSAGE)
                return
            with ui.element("div").style("display:flex;gap:10px;min-width:0;"):
                with labeled_field("Temperature", extra="flex:1;"):
                    _select(
                        options=[(f"{t:.1f}", f"{t:.1f}") for t in TEMPERATURE_CHOICES],
                        value=f"{view.draft.temperature:.1f}",
                        label="Temperature",
                        on_change=_sync(self._pick_temperature),
                        testid="temperature-select",
                        disabled=self._locked,
                    )
                with labeled_field("Seed", extra="flex:1;"):
                    _seed_input(
                        value=view.draft.seed,
                        on_change=_sync(self._set_seed),
                        disabled=self._locked,
                    )
            # Its own row rather than a third box in the one above: three
            # controls in a 430px column put the select at ~120px, which
            # clips "medium" at this font. Beside temperature and seed in
            # meaning all the same — it is pinned on every run this
            # evaluation launches, and provenance reports it there.
            with labeled_field(REASONING_LABEL):
                _select(
                    options=[(effort, effort) for effort in REASONING_EFFORTS],
                    value=view.draft.reasoning_effort,
                    label=REASONING_LABEL,
                    on_change=_sync(self._pick_reasoning_effort),
                    testid="reasoning-select",
                    disabled=self._locked,
                )
            ui.label(DETERMINISM_NOTE).classes("ink2").props('data-testid="determinism-note"').mark(
                "determinism-note"
            ).style(NOTE_STYLE)

    def _step_size(self) -> None:
        view = self._view
        with self._step(6):
            if view is None:
                _empty_line(UNSAVED_MESSAGE)
                return
            current = view.draft.size
            with ui.element("div").style("display:flex;gap:8px;min-width:0;"):
                radio_option(
                    f"Evaluation · all {format_count(view.corpus_record_count)}",
                    selected=current is EvaluationSize.FULL,
                    on_click=None
                    if self._locked
                    else _toggle(self._pick_size, EvaluationSize.FULL),
                )
                radio_option(
                    f"Dev · {format_count(view.dev_record_max)} records",
                    selected=current is EvaluationSize.DEV,
                    on_click=None if self._locked else _toggle(self._pick_size, EvaluationSize.DEV),
                )
            ui.label(SIZE_NOTE).classes("ink2").props('data-testid="size-note"').mark(
                "size-note"
            ).style(NOTE_STYLE)

    def _launch_row(self) -> None:
        """README §2: `margin-top:auto; display:flex; gap:8px` — the primary
        button (`flex:1`, the count following the model selection) beside the
        secondary "Preview prompt"."""
        view = self._view
        count = 0 if view is None else view.draft.launch_label_count
        can_launch = view is not None and view.can_launch
        with (
            ui.element("div")
            .props('data-testid="launch-row"')
            .mark("launch-row")
            .style("margin-top:auto;display:flex;gap:8px;min-width:0;")
        ):
            launch = (
                ui.element("button")
                .classes("btn primary")
                .props('type="button" data-testid="launch"')
                .mark("launch")
                .style("flex:1;justify-content:center;")
            )
            if can_launch:
                launch.on("click", _sync(self._launch))
            else:
                launch.props("disabled").style("opacity:.45;cursor:default;")
            with launch:
                ui.label(_launch_label(count))
            preview = (
                ui.element("button")
                .classes("btn secondary")
                .props('type="button" data-testid="preview-prompt"')
                .mark("preview-prompt")
            )
            if view is not None and view.draft.prompt_template_id is not None:
                preview.on("click", _sync(self._preview_prompt))
            else:
                preview.props("disabled").style("opacity:.45;")
            with preview:
                ui.label(PREVIEW_LABEL)

    # --- progress column -----------------------------------------------------

    def _render_progress(self) -> None:
        self._progress_header()
        self._progress_cards()
        self._runs_card()
        self._reproducibility_card()

    def _progress_header(self) -> None:
        with (
            ui.element("div")
            .props('data-testid="progress-header"')
            .style("display:flex;align-items:baseline;gap:14px;min-width:0;flex:none;")
        ):
            settled = "true" if self._settled else "false"
            ui.label(PROGRESS_TITLE_SETTLED if self._settled else PROGRESS_TITLE).classes(
                "lbl nowrap"
            ).props(f'data-testid="progress-title" data-settled="{settled}"').mark("progress-title")
            ui.label(PROGRESS_CAPTION).classes("mono ink3").props(
                'data-testid="progress-caption"'
            ).mark("progress-caption").style(
                "font-size:11px;overflow:hidden;text-overflow:ellipsis;"
            )

    def _progress_cards(self) -> None:
        view = self._view
        with (
            ui.element("div")
            .props('data-testid="progress-cards"')
            .style("display:flex;flex-direction:column;gap:12px;flex:none;min-width:0;")
        ):
            if view is None or not view.progress:
                with card(), ui.element("div").style("padding:12px 14px;"):
                    _empty_line(NO_RUNS_MESSAGE)
                return
            for progress in view.progress:
                progress_card(progress=progress)
                self._results_link(progress)

    def _results_link(self, progress: RunProgressView) -> None:
        """ "done · scored — See results", under the card it belongs to.

        Only for a run that **has** a board: a link to "Not scored yet" is
        the dead end this whole fix is about. Rendered beside the card rather
        than inside it, so `progress_card` keeps its one job and its frozen
        signature (`components/progress_card.py`).
        """
        if progress.run_id not in self._scored_runs:
            return
        with (
            ui.element("div")
            .props(f'data-testid="progress-scored" data-run="{progress.run_id}"')
            .mark("progress-scored")
            .style("display:flex;align-items:baseline;gap:8px;padding:0 2px;min-width:0;")
        ):
            ui.label(SCORED_MARKER).classes("mono ink3").props(
                'data-testid="progress-scored-marker"'
            ).style("font-size:10.5px;")
            link = ui.link(text=RESULTS_LINK_LABEL, target=f"/results?run={progress.run_id}")
            link.classes(remove="nicegui-link", add="mono")
            link.props('data-testid="progress-results-link"').mark("progress-results-link")
            link.style("font-size:10.5px;color:var(--ink);")

    def _runs_card(self) -> None:
        page = self._runs
        state = table_state(
            RUNS_TABLE, sort_key="started_at", sort_dir=SortDir.DESC, page_size=PAGE_SIZE
        )
        with card(extra="overflow:hidden;"):
            with card_header(title=RUNS_TITLE, count=self._runs_summary(), count_class="ink3"):
                self._discard_evaluation_action()
            with (
                ui.element("div")
                .props('data-testid="runs-well"')
                .style("overflow:auto;flex:none;min-width:0;"),
                ui.element("div").style(f"min-width:{RUNS_TABLE_MIN_WIDTH_PX}px;"),
            ):
                data_table(
                    columns=self._run_columns(),
                    rows=() if page is None else page.items,
                    state=state,
                    on_sort=_toggle_sort(self._sort_runs),
                    row_style=_run_row_style,
                    empty_message=NO_RUNS_MESSAGE,
                    testid="table-runs",
                )
            pagination_row(
                state=state,
                total=0 if page is None else page.total,
                shown=0 if page is None else len(page.items),
                on_page=_toggle_page(self._page_runs),
                on_page_size=None,
                page_sizes=(PAGE_SIZE,),
            )

    def _discard_evaluation_action(self) -> None:
        """ "Discard evaluation", in the header of the card whose rows each
        carry the per-run "discard" (`SD35`).

        **Not in the toolbar.** `SD32` settled that the right group holds
        exactly one secondary button in every state, and the one it holds is
        the creation affordance an analyst presses routinely; a destructive
        verb one gap away from it is a mis-click with no undo. The scope is
        also legible here and nowhere else: the header takes the whole list, a
        row takes its own row.

        **The action stays on screen while a run is active**, which is the one
        place it departs from the row version. A row hides its `discard` while
        it is `queued` or `running` because *that row is the obstacle* and
        there is nothing to say. An evaluation's obstacle is somewhere else in
        the table, so hiding the action would remove the only route with no
        explanation; it opens, and the dialog renders G1's refusal naming the
        run that caused it (§18.2, `DiscardPreviewView.active_detail`).
        """
        view = self._view
        if view is None:
            # No evaluation, no target. The toolbar's "New evaluation" is the
            # only thing to offer in that state (`SD32`).
            return
        _text_button(
            DISCARD_EVALUATION_LABEL,
            testid="evaluation-discard",
            on_click=_toggle(self._open_evaluation_discard, view.draft.evaluation_id),
        )

    def _runs_summary(self) -> str:
        """The header's "14 · 2 dev · 1 failed".

        Counted over the **whole** run list the service returned, not over the
        page on screen — the same shape as `import_view._files()`, which reads
        every file for a header count that is a property of the table rather
        than of its current page.
        """
        total = len(self._all_runs)
        dev = sum(1 for r in self._all_runs if r.is_dev)
        failed = sum(1 for r in self._all_runs if r.status is RunStatus.FAILED)
        return f"{format_count(total)} · {format_count(dev)} dev · {format_count(failed)} failed"

    def _run_columns(self) -> tuple[ColumnSpec[RunView], ...]:
        """README §2, "Runs table" — the five columns at their exact widths."""
        return (
            ColumnSpec(
                key="run_id",
                label="Run",
                width="74px",
                cell_class="td-clip",
                render=_render_run_id,
            ),
            ColumnSpec(
                key="model_tag",
                label="Model",
                width="132px",
                sortable=True,
                cell_class="td-clip",
                render=_render_model,
            ),
            ColumnSpec(
                key="records_done",
                label="Records",
                width="66px",
                align="right",
                sortable=True,
                cell_class="mono td-clip",
                render=_render_records,
            ),
            ColumnSpec(
                key="started_at",
                label="Start time",
                width="152px",
                sortable=True,
                cell_class="td-clip",
                render=_render_started,
            ),
            ColumnSpec(
                key="status",
                label="Status",
                width=STATUS_COLUMN_PX,
                sortable=True,
                render=self._render_status,
            ),
        )

    def _render_status(self, run: RunView) -> None:
        """ "done" / "running" / "queued" in `--ink3`, `FAILED` in `--danger`,
        each followed by a `DEV` chip in `--warn` when the run is dev-sized;
        a muted "log" action for any run that stopped with a reason; and —
        undrawn but required by sw-design.md §15.4 — an `interrupted` run's
        explicit **Resume**.

        The status word and the dev marker are **two elements, not one**
        (`_status_marker` has the reasoning). `data-status` and `data-dev`
        stay on the word: they are the service's two values verbatim, nothing
        is derived here, and they were the only place the two facts were both
        legible before the chip existed.
        """
        marker, tone = _status_marker(run)
        with ui.element("div").style("display:flex;align-items:center;gap:6px;min-width:0;"):
            ui.label(marker).classes(f"mono {tone}").props(
                f'data-testid="run-status" data-status="{run.status.value}" '
                f'data-dev="{"true" if run.is_dev else "false"}"'
            ).mark("run-status").style("font-size:11px;")
            if run.is_dev:
                ui.label(DEV_MARKER).classes("mono warn").props('data-testid="run-dev"').mark(
                    "run-dev"
                ).style("font-size:10.5px;")
            if run.is_resumable:
                _text_button("Resume", testid="run-resume", on_click=_toggle(self._resume, run))
            # Offered on **any** run carrying a reason, not only a failed one.
            # An interrupted run's reason is what decides whether Resume will
            # help — "the endpoint did not finish in time" and "nothing is
            # listening" produce the same row and the same button, and only
            # this sentence tells them apart.
            if run.error is not None:
                _text_button("log", testid="run-log", on_click=lambda: self._open_log(run))
            # Discard lives **in this cell**, not in a sixth column: this cell
            # already carries the row's secondary actions (README §2, and
            # `STATUS_COLUMN_PX` on what that has cost the drawn width).
            #
            # An active run gets **Stop** instead. G1's reasoning — "there is
            # nothing to offer while a worker is writing to the row"
            # (sw-design.md §18.5) — is right about *discard*, which destroys
            # rows the worker is still producing, and it left the one case
            # with no action at all: a launch against a model that answers a
            # record in minutes could only be escaped by waiting out the
            # endpoint bound or killing the process. Stop destroys nothing. It
            # ends the run and keeps every row it committed, which is the
            # `interrupted` state Resume already acts on.
            if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
                _text_button("Stop", testid="run-stop", on_click=_toggle(self._cancel, run))
            else:
                _text_button(
                    "discard",
                    testid="run-discard",
                    on_click=_toggle(self._open_discard, run),
                )

    def _reproducibility_card(self) -> None:
        provenance = None if self._view is None else self._view.provenance
        with card(extra="flex:none;"), ui.element("div").style("padding:12px 14px;"):
            ui.label(PROVENANCE_TITLE).classes("lbl").props('data-testid="provenance-title"').mark(
                "provenance-title"
            ).style("white-space:normal;")
            if provenance is None:
                _empty_line(NO_PROVENANCE_MESSAGE)
                return
            ui.label(_provenance_line(provenance)).classes("mono ink2").props(
                'data-testid="provenance-line"'
            ).mark("provenance-line").style(
                "font-size:11px;line-height:1.6;margin-top:6px;white-space:normal;"
            )

    # --- setup actions -------------------------------------------------------

    def _selected_corpus_id(self) -> str | None:
        if self._view is not None:
            return str(self._view.draft.corpus_id)
        pending = evaluation_setup().corpus_id
        if pending is not None and any(str(c.corpus_id) == pending for c in self._corpora):
            return pending
        return None if not self._corpora else str(self._corpora[0].corpus_id)

    def _selected_config_id(self) -> str | None:
        if self._view is not None:
            return str(self._view.draft.feature_config_id)
        pending = evaluation_setup().feature_config_id
        if pending is not None and any(str(s.feature_config_id) == pending for s in self._sets):
            return pending
        return None if not self._sets else str(self._sets[0].feature_config_id)

    def _remember(
        self,
        *,
        evaluation_id: str | None = None,
        corpus_id: str | None = None,
        feature_config_id: str | None = None,
    ) -> None:
        """Update this client's `EvaluationSetup`, **inside `_root`'s slot**.

        `app.storage.client` resolves through the slot stack, and an event
        handler's slot belongs to the element that fired it — an element this
        view's own `_render()` is entitled to have destroyed by the time the
        handler runs. `_root` is built once in `build()` and never cleared, so
        it outlives every redraw; without this wrapper a "Save draft" whose
        button was replaced by an in-flight redraw raises "The parent element
        this slot belongs to has been deleted" from the storage read, which is
        exactly the failure `import_view.reload`'s docstring records.
        """
        assert self._root is not None  # built in `build()`, before any handler
        with self._root:
            setup = evaluation_setup()
            set_evaluation_setup(
                EvaluationSetup(
                    evaluation_id=(
                        evaluation_id if evaluation_id is not None else setup.evaluation_id
                    ),
                    corpus_id=corpus_id if corpus_id is not None else setup.corpus_id,
                    feature_config_id=(
                        feature_config_id
                        if feature_config_id is not None
                        else setup.feature_config_id
                    ),
                )
            )

    def _runs_state(self) -> TableState:
        """The runs table's sort and page — read inside `_root`'s slot, for
        `_remember`'s reason."""
        assert self._root is not None
        with self._root:
            return table_state(
                RUNS_TABLE, sort_key="started_at", sort_dir=SortDir.DESC, page_size=PAGE_SIZE
            )

    def _set_runs_state(self, state: TableState) -> None:
        assert self._root is not None
        with self._root:
            set_table_state(RUNS_TABLE, state)

    async def _pick_corpus(self, value: str) -> None:
        if self._view is None:
            self._remember(corpus_id=value)
            await self.reload()
            return
        await self._update(corpus_id=CorpusId(value))

    async def _pick_feature_set(self, value: str) -> None:
        if self._view is None:
            self._remember(feature_config_id=value)
            await self.reload()
            return
        await self._update(feature_config_id=FeatureConfigId(value))

    async def _pick_template(self, value: str) -> None:
        await self._update(prompt_template_id=PromptTemplateId(value))

    async def _toggle_model(self, tag: str) -> None:
        view = self._view
        if view is None:
            return
        selected = list(view.draft.selected_models)
        if tag in selected:
            selected.remove(tag)
        else:
            selected.append(tag)
        await self._update(selected_models=tuple(selected))

    async def _pick_temperature(self, value: str) -> None:
        await self._update(temperature=float(value))

    async def _pick_reasoning_effort(self, value: str) -> None:
        await self._update(reasoning_effort=value)

    async def _set_seed(self, value: str) -> None:
        try:
            seed = int(value)
        except ValueError:
            # A non-integer never reaches the service; the redraw puts the
            # stored seed back in the box, which is the honest answer to
            # "what is this run's seed".
            await self.reload()
            return
        await self._update(seed=seed)

    async def _pick_size(self, size: EvaluationSize) -> None:
        await self._update(size=size)

    async def _update(self, **changes: object) -> None:
        """Persist one step. Every step saves as it is chosen (module
        docstring), so `EvaluationView.can_launch` is never out of step with
        what is on screen."""
        view = self._view
        if view is None:
            return
        try:
            await self._services.evaluation.update_draft(view.draft.evaluation_id, **changes)  # type: ignore[arg-type]
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
        await self.reload()

    async def _save_draft(self) -> None:
        """Re-save an **existing, unlaunched** draft.

        It no longer doubles as the create path: creating is
        `_new_evaluation`, and a label reading "Save draft" over a row that
        does not exist yet was half of what made this view unreadable
        (SD32). Every step already persists as it is chosen (module
        docstring), so this is the explicit confirmation of a setup that is
        on disk either way — which is the one thing it can honestly mean.
        """
        view = self._view
        if view is None:
            return
        try:
            await self._services.evaluation.update_draft(
                view.draft.evaluation_id, name=view.draft.name
            )
            ui.notify(DRAFT_SAVED_MESSAGE, type="positive")
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
        await self.reload()

    async def _new_evaluation(self) -> None:
        """Create an evaluation and make it the one this client is looking at.

        **One action with one meaning**, reached from the two states where the
        toolbar offers it, and doing the same thing in both:

        - *Nothing saved yet.* The row is created from the corpus and the
          frozen set steps 1 and 2 already show — both default to a concrete
          pick, so there is never a press that has nothing to cite.
        - *A launched evaluation on screen.* `_selected_corpus_id` and
          `_selected_config_id` return **that evaluation's** two ids, so the
          new draft cites the same corpus and the same frozen set. This is
          literally the "clone into a new evaluation" that
          `design/prompt-evaluation/README.md` §2 step 2 instructs, which
          until SD32 had nothing to clone into.

        No sentinel is needed in `EvaluationSetup` for either (SD32): the row
        exists before `reload()` runs, so `_current_evaluation` resolves the
        remembered id rather than falling back to `drafts[0]` — there is no
        "no evaluation selected, but evaluations exist" state to represent.

        `EvaluationService.save_draft` supplies the design's own defaults —
        the active template, temperature 0.0, seed 42, size `full` — so
        nothing here duplicates them, and the clone deliberately carries the
        *defaults* rather than the launched evaluation's decoding settings:
        copying those would make "same as the last run" a silent claim the
        controls no longer say out loud.
        """
        corpus_id = self._selected_corpus_id()
        config_id = self._selected_config_id()
        if corpus_id is None or config_id is None:
            return
        try:
            draft = await self._services.evaluation.save_draft(
                name=self._new_name(config_id),
                corpus_id=CorpusId(corpus_id),
                feature_config_id=FeatureConfigId(config_id),
            )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        self._remember(evaluation_id=str(draft.evaluation_id))
        ui.notify(EVALUATION_CREATED_MESSAGE, type="positive")
        await self.reload()

    def _new_name(self, config_id: str) -> str:
        """A new evaluation is named after the feature set it cites — the
        module docstring's rule, unchanged, and applied to the clone too.

        `evaluation.name` has no unique constraint and `save_draft` does not
        dedupe, so a clone and its original share a name **on purpose**: they
        pin the same set, the name is the only thing in the row that says so,
        and a "(2)" suffix invented here would be a fact about this view's
        history rather than about either evaluation (SD32). Nothing in the
        product identifies an evaluation by name; `evaluation_id` does that.
        """
        return next(s.name for s in self._sets if str(s.feature_config_id) == config_id)

    # --- launch, resume and polling -----------------------------------------

    async def _launch(self) -> None:
        """Pin the inputs and queue one run per selected model.

        Two service calls, in this order and for this reason (sw-design.md
        §15.2): `EvaluationService.launch` is the *transaction* — it snapshots
        `evaluation_feature`, resolves every fingerprint, stamps `launched_at`
        and creates the `queued` rows, or does none of it — and
        `RunService.launch_runs` is what submits the work the transaction
        created. Submitting before the commit would queue runs an aborted
        launch never made.
        """
        view = self._view
        if view is None:
            return
        evaluation_id = view.draft.evaluation_id
        try:
            await self._services.evaluation.launch(evaluation_id)
            await self._services.run.launch_runs(evaluation_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        await self.reload()
        self._start_polling()

    async def _resume(self, run: RunView) -> None:
        """An `interrupted` run is picked back up **explicitly** — nothing
        auto-restarts at app start (sw-design.md §15.4, §15 F8)."""
        try:
            await self._services.run.resume(RunId(run.run_id))
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        await self.reload()
        self._start_polling()

    async def _cancel(self, run: RunView) -> None:
        """Stop a run, keeping what it committed.

        No confirmation dialog, deliberately, and the contrast with `discard`
        two methods below is the reason: that one asks because it destroys
        rows and cannot be undone. This one destroys nothing — the run becomes
        `interrupted` with every extraction it managed still in place, and
        Resume picks it up from the hole. A dialog guarding a reversible act
        is a dialog people learn to click through.
        """
        try:
            await self._services.run.cancel(RunId(run.run_id))
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
        await self.reload()

    # --- discard (sw-design.md §18) -----------------------------------------

    async def _open_discard(self, run: RunView) -> None:
        """Read what would be lost, then ask.

        The preview is a service call rather than a count this view keeps:
        `RunView` carries `records_done`, not scores or mismatches, and a
        dialog that guessed at those would be a second, staler answer to the
        question the analyst is being asked to decide on.
        """
        run_id = RunId(run.run_id)
        try:
            preview = await self._services.lifecycle.run_preview(run_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        if self._root is None:
            return
        # Parented to `_root`, not to the runs card: every redraw replaces that
        # card, and a dialog parented to a destroyed element goes with it
        # (`_open_settings`'s own note).
        with self._root:
            dialog = cast(
                "ui.dialog",
                discard_dialog(
                    preview=preview,
                    on_discard=lambda force: self._discard(run_id, force=force),
                    on_export=(
                        None if not preview.has_exportable else lambda: self._export_run(run_id)
                    ),
                ),
            )
        # `dialog.value = True` rather than `.open()`: the N4 gate scans `ra2/`
        # for `.open(` and wants an `encoding=` beside it (Do-NOT #4).
        dialog.value = True

    async def _discard(self, run_id: RunId, *, force: bool) -> None:
        """`force` is G2 only. G1 has no override, and the service re-checks
        both — the dialog's disabled button is a UI state, not a guarantee."""
        try:
            await self._services.lifecycle.discard_run(run_id, force=force)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        ui.notify(f"Discarded run {run_id}.")
        await self.reload()

    async def _open_evaluation_discard(self, evaluation_id: EvaluationId) -> None:
        """The same read-then-ask as `_open_discard`, one scope up.

        `evaluation_preview` sums the counts over the evaluation's runs and
        carries G1 and G2 for all of them, so the dialog needs nothing this
        view would have to work out: an evaluation with no runs previews as
        all zeros and is discardable, and an evaluation holding an active run
        previews as `active` with the run that is in the way named.
        """
        try:
            preview = await self._services.lifecycle.evaluation_preview(evaluation_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        if self._root is None:
            return
        # The run ids are taken **now**, beside the counts the dialog is about
        # to render, rather than re-read when Export is pressed: reading them
        # twice is a second answer to the question the analyst was already
        # shown one answer to (`_open_discard`'s note about a staler count).
        run_ids = tuple(RunId(run.run_id) for run in self._all_runs)
        with self._root:
            dialog = cast(
                "ui.dialog",
                discard_dialog(
                    preview=preview,
                    on_discard=lambda force: self._discard_evaluation(evaluation_id, force=force),
                    on_export=(
                        None
                        if not preview.has_exportable
                        else lambda: self._export_evaluation(run_ids)
                    ),
                ),
            )
        dialog.value = True

    async def _discard_evaluation(self, evaluation_id: EvaluationId, *, force: bool) -> None:
        """`force` is G2 only, exactly as for a run — and the service re-checks
        both, because the dialog's disabled button is a UI state.

        Nothing here clears the remembered evaluation id: `_current_evaluation`
        already falls back to the newest evaluation that resolves, and to the
        empty state when none does. The runs table's **page** is reset, because
        the next reload shows a different evaluation's runs and page 3 of the
        discarded one names nothing in the new list.
        """
        name = UNKNOWN_VALUE if self._view is None else self._view.draft.name
        try:
            await self._services.lifecycle.discard_evaluation(evaluation_id, force=force)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            await self.reload()
            return
        state = self._runs_state()
        self._set_runs_state(TableState(state.sort_key, state.sort_dir, 1, state.page_size))
        ui.notify(EVALUATION_DISCARDED_MESSAGE.format(name=name))
        await self.reload()

    async def _export_run(self, run_id: RunId) -> None:
        """Both files, one press. They are two tables of one run, and asking
        an analyst which half of the evidence they want before a discard is a
        question with one sensible answer (§18.3)."""
        try:
            view = await self._services.lifecycle.run_export(run_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        self._download_run(view)

    async def _export_evaluation(self, run_ids: Sequence[RunId]) -> None:
        """Export before discarding an *evaluation*: the per-run pair, once per
        run (`SD35`).

        `LifecycleService.run_export` is the only export this slice has and it
        is per run. **The merge is not made here.** One file across three runs
        would need a `run_id` column, a rule for how two runs' score rows sit
        beside each other, and a header comment naming an evaluation rather
        than a run — three decisions about what the data means, which is
        `export_service`'s business and not this layer's (Do-NOT #7). Writing
        them in `ui/` would also make the evaluation's CSV a different shape
        from the one the same analyst gets from a row, for no reason but which
        button was pressed.

        A run that recorded neither a score nor a mismatch is skipped rather
        than written as two header-only files — the same rule `loss_line`
        applies to its zero counts, and the same one `has_exportable` states.
        """
        for run_id in run_ids:
            try:
                view = await self._services.lifecycle.run_export(run_id)
            except ServiceError as exc:
                ui.notify(str(exc), type="negative")
                return
            if not view.scores and not view.mismatches:
                continue
            self._download_run(view)

    def _download_run(self, view: RunExportView) -> None:
        """The two files a run leaves behind, named by run id so a bundle from
        an evaluation is still self-describing once it is on disk."""
        ui.download.content(
            self._services.export.run_scores_csv(view),
            f"{view.run_id}.scores.csv",
            media_type="text/csv",
        )
        ui.download.content(
            self._services.export.run_mismatches_csv(view),
            f"{view.run_id}.mismatches.csv",
            media_type="text/csv",
        )

    @property
    def _settled(self) -> bool:
        """Whether anything is still expected to move.

        Read from `_all_runs` — `RunService.list_runs` — rather than from
        `EvaluationView.progress`. The two used to disagree: `RunService`
        reclaimed on its read paths and `EvaluationService` built its progress
        cards straight from the rows, so one screen gave two answers about the
        same run and this property took the one that called a dead run live.

        That split is gone. Restart detection happens once, at process start
        (`RunService.reclaim_orphans`), so both services read rows that are
        already reconciled and neither can reclaim under the other. The read
        stays here because the runs table is where a run's status belongs;
        there is no longer a correctness reason for it, which is worth saying
        so nobody restores the old one by moving it back.

        **Both lists, not just `_all_runs`.** `refresh_progress` re-reads the
        paged `_runs` the table draws and the capped `_all_runs` this property
        judges as two separate queries, and a tick can land across a commit:
        the first read returns `queued`, the worker's row is committed, the
        second read returns `done`. Judging on `_all_runs` alone then stopped
        the timer *because everything was finished* while the table still
        showed the `queued` row the first read had returned — and nothing
        ticks again to correct it, so the screen stays wrong until the page is
        reloaded. That is the one state this property must never produce,
        because it is the one the user cannot get out of.

        Reading both closes it without the two queries having to be atomic: a
        torn tick leaves one list unsettled, so the timer survives to the next
        tick, where both reads fall on the same side of the commit and agree.
        A tick that changes nothing is what this poll is made of; a screen
        frozen on a stale row is not.
        """
        if self._view is None:
            return True
        paged = self._runs.items if self._runs is not None else ()
        return not any(
            r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in (*self._all_runs, *paged)
        )

    def _start_polling(self) -> None:
        """`ui.timer`, in `import_view._start_polling`'s shape — and
        unconditionally, for its reason: the work was submitted a moment ago
        and a read taken here can legitimately beat the worker's first write,
        so a `_settled` check at this point can be stale. The timer re-checks
        on every tick and stops itself the moment it is genuinely settled.

        **Two differences from Import**, both because an import takes seconds
        and a run takes hours.

        It calls `refresh_progress`, not `reload` — see that method for the
        ten-requests-a-second this was doing to the endpoint the worker was
        waiting on.

        And it slows down. `POLL_FAST_S` is right for the handshake, where the
        submit has just happened and the first write is imminent; it is absurd
        for a model answering one record every two minutes, where it means six
        hundred redraws between two numbers changing. After `POLL_FAST_TICKS`
        the interval moves to `POLL_SETTLED_S`. `ui.timer` re-reads `interval`
        before each sleep, so this takes effect on the next tick without
        tearing the timer down.
        """
        if self._poll is not None or self._root is None:
            return
        ticks = 0

        async def poll() -> None:
            nonlocal ticks
            await self.refresh_progress()
            ticks += 1
            if ticks == POLL_FAST_TICKS and self._poll is not None:
                self._poll.interval = POLL_SETTLED_S
            if self._settled and self._poll is not None:
                self._poll.deactivate()
                self._poll = None

        with self._root:
            self._poll = ui.timer(POLL_FAST_S, poll)

    # --- table actions -------------------------------------------------------

    async def _sort_runs(self, key: str) -> None:
        self._set_runs_state(self._runs_state().toggled(key))
        await self.reload()

    async def _page_runs(self, page: int) -> None:
        state = self._runs_state()
        self._set_runs_state(TableState(state.sort_key, state.sort_dir, page, state.page_size))
        await self.reload()

    # --- dialogs -------------------------------------------------------------

    async def _open_settings(self) -> None:
        """The Models footer's gear (README §2 step 4).

        The dialog is L3's and **brings its own `ui.dialog()`** — this hands
        it the read model and two callbacks, keeps the handle so "refresh" can
        close it, and reaches inside it for nothing else.

        Built inside `_root` for `import_view._open_intake`'s reason: this
        dialog's own gear lives in the models card, which every redraw
        replaces, and a dialog parented to a destroyed element goes with it.
        """
        connection = self._connection
        if connection is None or self._root is None:
            return
        with self._root:
            dialog = cast(
                "ui.dialog",
                ollama_settings_dialog(
                    settings=connection,
                    on_save=_save_settings,
                    on_refresh=_sync(self._refresh_connection),
                    on_test=self._test_connection,
                ),
            )
        self._settings_dialog = dialog
        # `dialog.value = True` is what `Dialog.open()` does, spelled out: the
        # N4 gate scans `ra2/` for `.open(` and wants an `encoding=` beside it
        # (Do-NOT #4), and a dialog opener tripping it would be a false
        # positive on a real invariant (`file_report_modal.show`'s note).
        dialog.value = True

    async def _test_connection(self, endpoint: str, timeout_s: int) -> ConnectionProbeView:
        """The settings dialog's "Test connection" — straight through to the
        service, which owns the probe and the loopback refusal.

        Nothing is decided here. The view does not know what a loopback host
        is, does not catch anything (`test_connection` never raises), and does
        not turn the result into words — the dialog's own `PROBE_WORDS` table
        does that. Business logic in `ui/` is Do-NOT #7.
        """
        return await self._services.evaluation.test_connection(endpoint, timeout_s)

    async def _refresh_connection(self) -> None:
        """ "Refresh model list" re-asks the endpoint. Reachability is
        re-checked here and on view load, **never on a timer**
        (plan-phase-3.md C3)."""
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog = None
        await self.reload()

    async def _preview_prompt(self) -> None:
        """ "Preview prompt" resolves the pinned inputs against the first
        record in scope and makes **no model call** (C4).

        The panel is L3's — one component, two entry points, and the token
        figure it renders is `≈ N tokens` because an exact count would need a
        tokeniser download (C6, R8).
        """
        view = self._view
        if view is None or view.draft.prompt_template_id is None or self._root is None:
            return
        try:
            scope = await self._services.evaluation.record_scope(view.draft.evaluation_id)
            if not scope:
                ui.notify(NO_RECORDS_MESSAGE, type="warning")
                return
            resolved = await self._services.prompt.preview(
                view.draft.prompt_template_id,
                view.draft.feature_config_id,
                RecordId(scope[0]),
                language=view.draft.prompt_language,
            )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        with (
            self._root,
            ui.dialog().props('data-testid="preview-dialog"') as dialog,
            dialog_card(extra="width:720px;max-height:88vh;overflow:auto;"),
            ui.element("div").style("padding:14px;"),
        ):
            prompt_preview_panel(resolved=resolved)
        dialog.value = True

    def _open_log(self, run: RunView) -> None:
        """The "log" action — the design's muted action in place of "results",
        now offered by any run that stopped with a reason rather than only by
        a failed one. `RunView.error` is what the worker stored; nothing is
        derived from it here."""
        if self._root is None:
            return
        with (
            self._root,
            ui.dialog().props('data-testid="run-log-dialog"') as dialog,
            dialog_card(extra="width:620px;max-height:88vh;overflow:auto;"),
        ):
            with card_header(title=f"Run {run.run_id}", count=run.model_tag, count_class="ink3"):
                pass
            with ui.element("div").style("padding:12px 14px;"):
                ui.label(run.error or EMPTY_CELL).classes("mono").props(
                    'data-testid="run-log-text"'
                ).mark("run-log-text").style(
                    "font-size:11.5px;white-space:pre-wrap;line-height:1.6;color:var(--danger);"
                )
        dialog.value = True


# --- cell renderers ----------------------------------------------------------


def _render_run_id(run: RunView) -> None:
    """ "run 2", linking to Results — a **placeholder route** this phase. An
    affordance that lands on "Not built in phase 1" is honest; a missing one
    is not.

    The design's fixtures use ids like `r-0403`, which fit the 74px this
    column is allotted (README §2). Real ids are uuid7 — 36 characters in a
    `table-layout:fixed` cell, and fixed layout does not clip, so the id ran
    straight through the Model column beside it.

    Clipping alone would not have been enough. uuid7 opens with a millisecond
    timestamp, so runs launched together share their first eleven characters
    and a truncated id distinguishes nothing; the *last* eight would, and read
    as noise. The ordinal is what this product already calls a run everywhere
    a person has to name one — `mismatch_service._run_label`'s "run 2 ·
    qwen3:14b", and the discard dialog's lead sentence. The full id stays on
    the link's `title`, which is where an id belongs when it is wanted for
    copying rather than for reading.
    """
    link = ui.link(text=f"run {run.ordinal}", target=f"/results?run={run.run_id}")
    link.classes(remove="nicegui-link", add="mono")
    link.props('data-testid="run-link"').mark("run-link")
    # `title` through the mapping, never interpolated into a props string
    # (`SD31`, `data_props`): `Props.parse` reads a quoted value as Python
    # source, and this one is an id that did not come from this file.
    data_props(link, {"title": str(run.run_id)})
    link.style("font-size:11.5px;color:var(--ink);")


def _render_model(run: RunView) -> None:
    ui.label(run.model_tag).classes("mono ink2").props('data-testid="run-model"').mark(
        "run-model"
    ).style("font-size:11.5px;display:block;overflow:hidden;text-overflow:ellipsis;")


def _render_records(run: RunView) -> None:
    text = EMPTY_CELL if run.status is RunStatus.QUEUED else format_count(run.records_done)
    ui.label(text).props('data-testid="run-records"').mark("run-records")


def _render_started(run: RunView) -> None:
    ui.label(_timestamp(run.started_at)).classes("mono ink3").props(
        'data-testid="run-started"'
    ).mark("run-started").style("font-size:11.5px;")


def _status_marker(run: RunView) -> tuple[str, str]:
    """The Status cell's text and its colour class (README §2, "Runs table").

    `FAILED` keeps the design's uppercase marker in `--danger`; every other
    state is the service's own status word in `--ink3`.

    **`DEV` is no longer one of the answers here.** The design draws it as
    *replacing* the status word, which is sound on a board where a dev-sized
    run is the exception — and wrong on this one. `RA2_DEV_RECORD_MAX` is 50
    and the development seed is 12 records, so *every* run an analyst makes
    while learning the product is dev-sized and this column rendered one
    constant string: a running run, a done run and an interrupted run were
    the same cell. A column that cannot tell those apart is not a status
    column, and the `data-status` attribute this cell also carries meant the
    distinction was legible to the test suite and to nobody else.

    The marker moves to a chip beside the word (`_render_status`), so both
    facts are on screen; the `--warn-soft` row tint the design also specifies
    is unchanged, and nothing about a dev run is quieter than it was.
    """
    if run.status is RunStatus.FAILED:
        return "FAILED", "danger"
    return run.status.value, "ink3"


def _run_row_style(run: RunView) -> str:
    """README §2: dev-sized runs `--warn-soft`, failed runs `--danger-soft`."""
    if run.status is RunStatus.FAILED:
        return "background:var(--danger-soft);"
    if run.is_dev:
        return "background:var(--warn-soft);"
    return ""


def _timestamp(value: datetime | None) -> str:
    return EMPTY_CELL if value is None else format_local(value, TIMESTAMP_FORMAT)


def _provenance_line(provenance: ProvenanceView) -> str:
    """Every field `mvp-spec.md` §19.8 requires, in the order the design's
    reproducibility card lists them. A field the run does not carry reads
    "unknown" rather than dropping its line — an unreproducible run has to
    say so (`ProvenanceView`'s own docstring)."""
    fingerprints = " + ".join(
        f"{key} {value[:8]}" for key, value in sorted(provenance.feature_fingerprints.items())
    )
    return " · ".join(
        (
            f"{provenance.model_name} + {provenance.model_digest}",
            f"prompt template v{provenance.prompt_template_version} "
            f"{provenance.prompt_template_fingerprint[:8]}",
            f"temperature {provenance.temperature:.1f}",
            f"seed {provenance.seed}",
            f"cfg {provenance.feature_config_id}" + (f" + {fingerprints}" if fingerprints else ""),
            f"corpus {provenance.corpus_id} v{provenance.corpus_version}",
            f"host {provenance.host_platform}",
            f"gpu {provenance.gpu_name or UNKNOWN_VALUE}",
            f"endpoint {_endpoint_text(provenance.llm_endpoint)}",
            # Beside temperature and seed, which is where it belongs: it
            # decides the answer as much as they do, and a run that asked
            # the model to think and one that did not must not read the
            # same here.
            f"reasoning {provenance.llm_reasoning_effort or UNKNOWN_VALUE}",
        )
    )


def _corpus_label(corpus: CorpusView) -> str:
    return f"corpus {corpus.name} · v{corpus.version} · {format_count(corpus.record_count)} records"


def _set_label(summary: FeatureSetSummary) -> str:
    return f"set · {summary.name} v{summary.version}"


def _launch_label(count: int) -> str:
    """ "Launch 3 runs" — the count follows the model selection (README §2)."""
    return f"Launch {count} run" + ("" if count == 1 else "s")


def _endpoint_text(endpoint: str) -> str:
    """The configured endpoint as the design's reproducibility card already
    spells it — `127.0.0.1:11434/v1`, host and path, no scheme.

    **This is a shim, and it is here rather than in the test that forces it**
    (CLAUDE.md, the ownership rule). J6 (`tests/e2e/test_j6_egress.py`, A5's)
    scans the served HTML for `(?:https?:)?//…` and allows only the server
    under test, bare `127.0.0.1` and bare `localhost` — it compares on
    *netloc*, so `http://127.0.0.1:11434/v1` reads as a foreign host purely
    because of its port. The URL is loopback and nothing dereferences it; it
    is a label. Phase 1 had no endpoint to name, so the case never arose.

    Dropping the scheme is not a workaround so much as the design's own other
    spelling: `Evaluation.dc.html`'s reproducibility card already writes
    "endpoint 127.0.0.1:11434" while its step 4 writes the full URL, and one
    spelling for both is better than two. The amendment in
    `contracts/amendments/feat-p3-evaluation-view.md` proposes J6 compare
    loopback on **hostname** instead, which would let step 4 render the URL
    verbatim; until that lands, this is what keeps the gate honest without
    editing someone else's file.
    """
    for scheme in ("https://", "http://"):
        if endpoint.startswith(scheme):
            return endpoint[len(scheme) :]
    return endpoint


def _gigabytes(value: int) -> str:
    """`8_500_000_000` -> `"8.5 GB"`. Presentation only, exactly like
    `format_count`: the byte count is always a service's."""
    return f"{value / 1_000_000_000:.1f} GB"


# --- small shared widgets ----------------------------------------------------


def _empty_line(message: str) -> Element:
    """The standard empty note: one `--ink2` line where the control would be.

    Empty states are undesigned in the mock and plan-phase-3.md C3 settles
    them as "the standard phase-1/2 empty card, no new pattern".
    """
    return (
        ui.label(message)
        .props('data-testid="empty-note"')
        .mark("empty-note")
        .style("padding:6px 2px;font-size:12px;color:var(--ink2);line-height:1.5;")
    )


def _text_button(text: str, *, testid: str, on_click: Callable[[], None]) -> Element:
    button = (
        ui.element("button")
        .classes("mono ink3")
        .props(f'type="button" data-testid="{testid}"')
        .mark(testid)
        .style(
            "background:none;border:none;padding:0;font-size:10.5px;cursor:pointer;"
            "text-decoration:underline;"
        )
    )
    button.on("click", lambda _: on_click())
    with button:
        ui.label(text)
    return button


def _select(
    *,
    options: Sequence[tuple[str, str]],
    value: str,
    label: str,
    on_change: Callable[[str], None],
    testid: str,
    disabled: bool = False,
) -> Element:
    """The design's `.sel`: a full-width select, mono 11.5px, with the
    browser's own caret. A native control for the same reason
    `features_view._select` uses one — the fidelity note asks for
    high-fidelity *layout*, medium-fidelity styling, and a native select is
    keyboard-reachable for free."""
    element = data_props(
        ui.element("select")
        .classes("rof")
        .props(f'data-testid="{testid}"')
        .mark(testid)
        .style(SEL_STYLE),
        {"aria-label": label},
    )
    if disabled:
        element.props("disabled").style("color:var(--ink3);background:var(--field-tint);")
    else:
        element.on(
            "change",
            lambda event: on_change(str(event.args)),
            js_handler="(e) => emit(e.target.value)",
        )
    with element:
        for option_value, text in options:
            # Through the mapping, not `html.escape` into the props string:
            # an option value is a corpus id, a feature-set id or a model tag,
            # and the string is parsed as Python before anything HTML-shaped
            # gets a chance to matter (SD31/SD34).
            option = data_props(ui.element("option"), {"value": option_value})
            if option_value == value:
                option.props("selected")
            with option:
                ui.label(text)
    return element


def _seed_input(*, value: int, on_change: Callable[[str], None], disabled: bool) -> Element:
    """The Seed field: typed, with the design's mono `edit` hint beside it."""
    with ui.element("div").style("display:flex;align-items:center;gap:6px;min-width:0;"):
        element = (
            ui.element("input")
            .classes("rof mono")
            .props('type="number" step="1" aria-label="Seed" data-testid="seed-input"')
            .mark("seed-input")
            .style(f"{SEL_STYLE}flex:1;min-width:0;")
        )
        # Through the props *dict*, never the props string: the string is
        # parsed, so a value the parser chokes on silently drops the element
        # (`features_view._text_input` documents the same trap).
        element.props["value"] = str(value)
        if disabled:
            element.props("disabled")
        else:
            element.on(
                "change",
                lambda event: on_change(str(event.args)),
                js_handler="(e) => emit(e.target.value)",
            )
        ui.label("edit").classes("mono ink3").style("font-size:10px;flex:none;")
    return element


def _save_settings(endpoint: str, timeout_s: int) -> None:
    """`ollama_settings_dialog`'s `on_save` (L3's frozen signature).

    The endpoint and the timeout are `Settings` values — `RA2_LLM_BASE_URL`
    and `RA2_LLM_TIMEOUT_S` — and nothing in phase 3 persists a setting from
    the UI: there is no service that writes one, and `ui/` may not reach
    `infra`. So the dialog reports where the change actually has to be made
    rather than accepting the edit and silently dropping it.
    """
    ui.notify(
        f"Set RA2_LLM_BASE_URL={endpoint} and RA2_LLM_TIMEOUT_S={timeout_s}, then restart.",
        type="warning",
    )


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to a sync callback type — the identical typing
    formality `features_view._sync` documents."""
    return cast("Callable[P, None]", action)


def _toggle[T](action: Callable[[T], Awaitable[None]], argument: T) -> Callable[[], None]:
    """Bind one argument to an async handler and hand back the nullary
    callback the component kit's `on_click`/`on_change` expect."""
    return cast("Callable[[], None]", lambda: action(argument))


def _toggle_sort(action: Callable[[str], Awaitable[None]]) -> Callable[[str], None]:
    return cast("Callable[[str], None]", action)


def _toggle_page(action: Callable[[int], Awaitable[None]]) -> Callable[[int], None]:
    return cast("Callable[[int], None]", action)
