# STUB — bodies owned by Z1 (feat/p5-mismatches-view). Not frozen.
"""Mismatches — the eighth nav entry and the last capability (F11).

`mvp-spec.md` §12: *"Presented as a flat, sortable, exportable list."* The
first word is the instruction, and `plan-phase-5.md` §3.2 is this view's
design — there is no design handoff for this screen, and that section is what
replaces one (C1, §15 F1).

**A module, not a package**, where Results is a package (`SD22`, §17.9). The
reasoning there was that three tabs built by three agents in one wave need
three files; here one screen is built by one agent in a wave of one, and a
package would be ceremony.

**Built from what already exists.** The reference is Census: a filter toolbar
over one wide sortable table with an export. `data_table` with fixed-width
`ColumnSpec`s, `pagination_row`, `field_select` per filter, `segmented_control`
for the inline three-way tag, `chip` for the anonymisation marking, `card` +
`card_header` for the tally strip, `chrome.empty_card` for the empty states.
**If this view finds itself needing a new component, a new colour or a second
table scale, that is the signal to stop and raise it** (R2) — not to invent
one where there is no designer to answer to.

**The evaluation resolution is not re-derived here.** Read
`ui/views/results/__init__.py` and reuse its shape: `/mismatches?evaluation=<id>`
with `&run=` and `&feature=`, and the standard empty card listing launched
evaluations when the parameter is absent.

Three empty states, and the third is the one that matters: no evaluation ·
nothing scored yet · **no mismatches at all, which is a good result and must
not read like an error**.

The usual rules. No business logic (Do-NOT #7): every count, every narrowed
tag and every "is this row reviewed" arrives already decided from
`MismatchService`; what lives here is the **words** for `MismatchTag` — one
rendering table, exactly as `FindingCode` and `ProbeCode` work, and the reason
§12's own "record error" and the enum's `structured_data_error` can both be
right (C4). No module-level mutable state (Do-NOT #8): the filters, the sort
and the page live in `app.storage.client`.

**M35 froze the signature; Z1 wrote the body**, plus plan-phase-5.md §6.1's
two declared exceptions — the `mismatches` `built` flag in `shell.py` and its
line in `views/__init__.py`, and the one deep link in
`ui/views/results/extraction_tab.py`.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Final, cast

from nicegui import ui
from nicegui.element import Element

from ra2.domain.ids import EvaluationId, FeatureId, MismatchId, RunId
from ra2.domain.mismatch import MismatchTag, ReviewTally, TagFilter, TagState
from ra2.services.container import Services
from ra2.services.errors import NotFoundError, RunNotScoreableError
from ra2.services.readmodels import (
    MismatchListView,
    MismatchRowView,
    ReviewTallyView,
    ScoringStatusView,
    SortDir,
)
from ra2.ui.components import ColumnSpec, card, card_header, chip, data_table, pagination_row
from ra2.ui.components.primitives import data_props, segmented_control
from ra2.ui.shell import item_for_key, shell
from ra2.ui.state import (
    MismatchesState,
    TableState,
    mismatches_state,
    set_mismatches_state,
    set_table_state,
    table_state,
)
from ra2.ui.views.results.chrome import empty_card, run_descriptor
from ra2.ui.views.scoring_states import NOT_SCORED_BODY as _NOT_SCORED_BODY
from ra2.ui.views.scoring_states import NOT_SCORED_TITLE as _NOT_SCORED_TITLE
from ra2.ui.views.scoring_states import (
    POLL_FAST_S,
    POLL_SLOW_S,
    RESCORE_STARTED,
    ScoringCard,
    card_for,
    rescore_row,
    run_label,
)

__all__ = [
    "MISMATCH_TABLE",
    "OTHER_LABEL",
    "PAGE_SIZE",
    "TAG_LABELS",
    "register",
    "tally_sentence",
]

_ITEM: Final = item_for_key("mismatches")

#: README §2's layout, reused: the Census shape, because this view's job is
#: the same one (Q1).
CONTENT_PADDING: Final = "16px 28px 24px"
CONTENT_GAP: Final = "14px"

#: One `TableState`, so this table's sort and page are its own.
MISMATCH_TABLE: Final = "mismatches.rows"

#: `P5-D4` — the Census number. §3.2 named 10 and "1–25 of 162" in one cell and
#: both halves come from Census, whose page size is 25.
PAGE_SIZE: Final = 25
DEFAULT_SORT_KEY: Final = "feature"
DEFAULT_SORT_DIR: Final = SortDir.ASC

#: `MismatchTag` -> the words on the screen. **The one rendering table**, the
#: same arrangement `FindingCode` and `ProbeCode` have: the enum values are the
#: stable identifiers that tests assert on, and the wording lives here.
#:
#: `structured_data_error` reads as **"record error"** because that is what
#: mvp-spec.md §12's own example calls it — *"of 40 reviewed, 32 hallucination,
#: 8 record error"* — and the spec and the screen have to agree without the
#: identifier moving (C4).
TAG_LABELS: Final[dict[MismatchTag, str]] = {
    MismatchTag.HALLUCINATION: "Hallucination",
    MismatchTag.STRUCTURED_DATA_ERROR: "Record error",
    MismatchTag.UNCLEAR: "Unclear",
}

#: What a stored tag `MismatchTag` does not name renders as. Nothing in the MVP
#: writes one (the wire is closed, §17.5); such a row shows its stored value
#: verbatim in the Tag cell and is counted under this heading in the strip.
OTHER_LABEL: Final = "Other"

#: The Tag filter's six options, in the order the toolbar offers them: the
#: three states, then the three tags. The **values** are `TagState` and
#: `MismatchTag` values — disjoint, so one field carries either (§17.5).
TAG_FILTER_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    (TagState.ANY.value, "tag · all"),
    (TagState.UNTAGGED.value, "tag · untagged"),
    (TagState.TAGGED.value, "tag · reviewed"),
    *((tag.value, f"tag · {TAG_LABELS[tag].lower()}") for tag in MismatchTag),
)

# --- copy -------------------------------------------------------------------

TOOLBAR_CAPTION: Final = "The structured record is authoritative in every case."
EXPORT_LABEL: Final = "Export CSV"
CLEAR_LABEL: Final = "Clear tag"
TALLY_TITLE: Final = "Review tally · per feature"

EMPTY_TITLE: Final = "No evaluation selected."
EMPTY_BODY: Final = (
    "Mismatches are reviewed one evaluation at a time. Open one from Results, "
    "or follow a run from the Evaluation view."
)
#: **One sentence, two screens.** This module had its own "Not scored yet."
#: and its own body; Results had another pair, and this plan would have made
#: four. They live in `views/scoring_states.py` now and are re-exported here
#: so the existing imports and tests keep working
#: (`plan-scoring-visibility-follow-ups.md` Part 1, step 1e).
NOT_SCORED_TITLE: Final = _NOT_SCORED_TITLE
NOT_SCORED_BODY: Final = _NOT_SCORED_BODY
#: The third empty state, and the reason it has its own wording: **this is a
#: good result**. A run with nothing wrong in it must not render like a
#: failure, an error or a missing page — R2's warning applied to copy.
NO_MISMATCHES_TITLE: Final = "No mismatches in this run."
NO_MISMATCHES_BODY: Final = "Every labelled feature this model answered, it answered correctly."
#: Distinct from the above, and deliberately so: a filter that matches nothing
#: is not a result about the run, it is a fact about the filter.
NO_MATCHES_MESSAGE: Final = "No mismatches match this filter."
NOTHING_REVIEWED: Final = "none reviewed yet"

#: How much of a record id the 190px column holds beside its chip.
RECORD_ID_CHARS: Final = 14
EMPTY_CELL: Final = "—"

# --- layout, the Census toolbar's own inline styles --------------------------

TOOLBAR_STYLE: Final = "display:flex;align-items:center;gap:10px;flex-wrap:wrap;"
LEFT_GROUP_STYLE: Final = (
    "display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;position:relative;"
)
RIGHT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;margin-left:auto;flex:none;"
TALLY_ROW_STYLE: Final = "display:flex;gap:14px;flex-wrap:wrap;"

_MENU_STYLE: Final = (
    "position:absolute;top:100%;left:0;margin-top:4px;z-index:20;min-width:100%;"
    "display:flex;flex-direction:column;padding:4px 0;background:var(--surface);"
    "border:1px solid var(--rule);border-radius:3px;"
)
_MENU_ITEM_STYLE: Final = (
    "display:block;width:100%;text-align:left;background:none;border:none;"
    "padding:5px 10px;font-family:var(--mono);font-size:11px;color:var(--ink);"
    "cursor:pointer;white-space:nowrap;"
)
_MENU_ITEM_ON_STYLE: Final = "background:var(--accent-soft);font-weight:500;"


def tally_sentence(tally: ReviewTally) -> str:
    """mvp-spec.md §12's own wording: *"of 40 reviewed, 32 hallucination, 8
    record error"*.

    **Copy, not arithmetic.** Every number here arrives made, from
    `domain.mismatch.tally`; this chooses words for them. That is the same
    division `FindingCode` has, and it is why `structured_data_error` can read
    as "record error" without the identifier moving (C4).

    A bucket at zero is left out rather than printed — the spec's example
    names two of three tags and does not say "0 unclear".
    """
    parts = [f"{count} {TAG_LABELS[tag].lower()}" for tag, count in tally.counts.items() if count]
    if tally.other:
        parts.append(f"{tally.other} {OTHER_LABEL.lower()}")
    if not parts:
        return NOTHING_REVIEWED
    return f"of {tally.reviewed} reviewed, " + ", ".join(parts)


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page(evaluation: str = "", run: str = "", feature: str = "") -> None:
        page = _MismatchesPage(services)
        await page.build(evaluation=evaluation, run=run, feature=feature)


class _MismatchesPage:
    """One client's Mismatches view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (Do-NOT #8). It holds only what it last
    read from a service, plus which dropdown is open.

    No business logic (Do-NOT #7): every row, count, narrowed tag and
    "is this reviewed" arrives already decided from `MismatchService`. What
    lives here is the words for them.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._view: MismatchListView | None = None
        #: One status per run of this evaluation — **not** a boolean over all
        #: of them. `any(is_scored)` was enough to decide whether to render a
        #: table, and not enough to decide anything about the run actually on
        #: screen: with run 1 scored and run 2's pass crashed, picking run 2
        #: produced an empty list, and an empty list is rendered as "No
        #: mismatches in this run. Every labelled feature this model answered,
        #: it answered correctly." A false sentence, on the screen where a
        #: human decides which model to believe
        #: (`plan-scoring-visibility-follow-ups.md` Part 1).
        self._statuses: tuple[ScoringStatusView, ...] = ()
        self._missing = ""
        self._open_menu: str | None = None
        self._toolbar: Element | None = None
        self._table_slot: Element | None = None
        self._tally_slot: Element | None = None
        self._root: Element | None = None
        self._poll: ui.timer | None = None

    # --- lifecycle ---------------------------------------------------------

    async def build(self, *, evaluation: str, run: str, feature: str) -> None:
        """Resolve the query parameters, then draw.

        `/mismatches?evaluation=<id>` with optional `&run=` and `&feature=`
        (§17.6) — the shape `ui/views/results/__init__.py` already implements,
        reused rather than re-derived. A URL naming a different evaluation
        resets the filters: a feature or a run from another evaluation names
        nothing in this one.
        """
        state = mismatches_state()
        if evaluation and evaluation != state.evaluation_id:
            state = MismatchesState(evaluation_id=evaluation)
        elif evaluation:
            state.evaluation_id = evaluation
        if run:
            state.run_id = run
        if feature:
            state.feature_id = feature
        set_mismatches_state(state)
        if evaluation:
            _reset_page()

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
            root = ui.element("div").style(
                f"display:flex;flex-direction:column;gap:{CONTENT_GAP};"
                "flex:1;min-height:0;min-width:0;"
            )
            with root:
                self._toolbar = (
                    ui.element("div").props('data-testid="mismatch-toolbar"').style(TOOLBAR_STYLE)
                )
                self._table_slot = ui.element("div").style(
                    "flex:1;min-height:0;min-width:0;display:flex;flex-direction:column;"
                )
                self._tally_slot = ui.element("div").style(TALLY_ROW_STYLE)
            self._root = root
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything and redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated — the shape every view in this app uses.
        """
        state = mismatches_state()
        self._view = None
        self._statuses = ()
        self._missing = ""
        if state.evaluation_id:
            evaluation_id = EvaluationId(state.evaluation_id)
            try:
                # **Two services, and that is not the edge §17.3 forbids.**
                # "Not scored yet" and "nothing was wrong" are different facts
                # and must not share a rendering (§16.7), and only the scoring
                # status tells them apart. The absent edge is
                # `mismatch_service` -> a scoring module; a *view* composing
                # two services is what the container exists for, and the
                # Results view already reads this same call.
                self._statuses = await self._services.results.scoring_status(evaluation_id)
                table = _state()
                self._view = await self._services.mismatch.list_mismatches(
                    evaluation_id,
                    run_id=RunId(state.run_id) if state.run_id else None,
                    feature_id=FeatureId(state.feature_id) if state.feature_id else None,
                    tag_state=_tag_filter(state.tag_state),
                    sort_key=table.sort_key,
                    sort_dir=table.sort_dir,
                    page=table.page,
                    page_size=table.page_size,
                )
            except NotFoundError:
                self._missing = state.evaluation_id
                self._view = None
        self._render()
        self._start_polling()

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        assert self._toolbar is not None
        assert self._table_slot is not None
        assert self._tally_slot is not None
        self._toolbar.clear()
        self._table_slot.clear()
        self._tally_slot.clear()

        view = self._view
        if view is None:
            with self._table_slot:
                empty_card(
                    EMPTY_TITLE if not self._missing else f"No evaluation {self._missing}.",
                    EMPTY_BODY,
                )
            return
        # **The toolbar first, and unconditionally.** It carries the run
        # chip, so a screen that drops it because *this* run has no scores
        # strands the analyst on that run with no way to reach the ones that
        # do. The old code got away with it by asking about the evaluation
        # rather than the run.
        with self._toolbar:
            self._filter_toolbar(view)

        card = self._scoring_card(view)
        with self._table_slot:
            if card is not None:
                # This run has no list to show, and the reason is not "it was
                # clean". `scoring_states` owns the sentence, so Results and
                # this screen cannot end up with two accounts of one fact.
                empty_card(card.title, card.body)
                if card.offers_rescore:
                    rescore_row(
                        [(view.filters.run_id, self._ordinal(view, view.filters.run_id))],
                        on_rescore=self._rescore,
                    )
            elif view.rows.total == 0 and not _is_filtered():
                # **A good result, and it must not read like an error** —
                # not an empty table, not a missing page, not a toast. It is
                # only reachable now when the run really was scored.
                empty_card(NO_MISMATCHES_TITLE, NO_MISMATCHES_BODY)
            else:
                self._table_card(view)
        with self._tally_slot:
            if card is None and view.tallies:
                self._tally_strip(view.tallies)

    # --- the poll -----------------------------------------------------------

    def _start_polling(self) -> None:
        """Re-read while a run or a pass is still moving, then stop.

        `results/__init__._start_polling`, and it is here for the sentence:
        "Scoring starts automatically the moment it does, **and this page
        refreshes itself**" is now one string shared by both screens, so
        either both refresh or the string is a lie on one of them.

        Fast while a pass is in flight, slow while waiting for a run — a pass
        is 0.14 s on the development seed and a run is hours, and the slow
        interval is what keeps a page left open during a run off the SQLite
        file the worker is committing to.
        """
        if self._root is None:
            return
        if self._settled:
            if self._poll is not None:
                self._poll.deactivate()
                self._poll = None
            return
        if self._poll is not None:
            self._poll.interval = self._interval
            return

        async def poll() -> None:
            await self.reload()

        with self._root:
            self._poll = ui.timer(self._interval, poll)

    @property
    def _settled(self) -> bool:
        """Whether anything this screen shows is still expected to change.

        A run that has not finished, or a pass in flight — the run's own
        terminal `done` is what submits the pass (`SD17`), so a page watching
        a running run is waiting for two things in sequence.
        """
        return not any(s.running or not s.is_finished for s in self._statuses)

    @property
    def _interval(self) -> float:
        return POLL_FAST_S if any(s.running for s in self._statuses) else POLL_SLOW_S

    # --- the scoring state --------------------------------------------------

    def _scoring_card(self, view: MismatchListView) -> ScoringCard | None:
        """Which scoring sentence this **run** deserves, or `None` for a list.

        Per run, because that is the unit the screen shows (`SD26`, §17.6:
        there is no "all runs" option) and the unit a scoring pass runs over.
        An evaluation-wide `any(is_scored)` answered a different question than
        the one the screen asks.

        A run with no status row at all — which nothing in the product
        produces, since `scoring_status` covers the evaluation's runs — is
        treated as "show the list", because inventing a refusal for an
        impossible state is how a real state ends up hidden behind it.
        """
        status = next(
            (s for s in self._statuses if s.run_id == view.filters.run_id),
            None,
        )
        return None if status is None else card_for(status)

    def _ordinal(self, view: MismatchListView, run_id: RunId) -> int:
        """The run's place in its evaluation, **as this screen already names
        it**: the run chip reads "run 1 · qwen3:14b" off the position in
        `view.runs`, and the Re-score button under the card has to say the
        same number as the chip above it."""
        for index, run in enumerate(view.runs, start=1):
            if run.model_id == run_id:
                return index
        return 0

    async def _rescore(self, run_id: RunId, ordinal: int) -> None:
        """Submit the pass and redraw — `results/__init__._rescore`, and
        deliberately the same: one verb, one seam, one sentence."""
        try:
            await self._services.scoring.submit_rescore(run_id)
        except (NotFoundError, RunNotScoreableError) as error:
            ui.notify(str(error))
            await self.reload()
            return
        ui.notify(RESCORE_STARTED.format(run=run_label(ordinal)))
        await self.reload()

    # --- the filter toolbar -------------------------------------------------

    def _filter_toolbar(self, view: MismatchListView) -> None:
        with ui.element("div").style(LEFT_GROUP_STYLE):
            self._run_chip(view)
            self._feature_chip(view)
            self._tag_chip()
            ui.label(TOOLBAR_CAPTION).props('data-testid="toolbar-caption"').style(
                "font-size:12px;color:var(--ink2);"
            )
        with ui.element("div").style(RIGHT_GROUP_STYLE):
            self._scored_at(view)
            run_descriptor(view.descriptor)
            self._export_button()

    def _run_chip(self, view: MismatchListView) -> None:
        """Which run this list shows.

        **There is no "all runs" option** (`SD26`, §17.6): a list mixing two
        models' mismatches for one record and feature is the cross-model
        agreement §16.9 defers, so the chip switches between runs rather than
        widening to all of them.
        """
        current = view.filters.run_id
        self._dropdown(
            name="run",
            text=view.run_label,
            aria_label="Run",
            options=[
                (
                    run.model_id,
                    f"run {index} · {run.tag}",
                    run.model_id == current,
                )
                for index, run in enumerate(view.runs, start=1)
            ],
            on_pick=self._pick_run,
        )

    def _feature_chip(self, view: MismatchListView) -> None:
        """ "feature · all 6 ▼". The options are **not** narrowed by the
        current filter: a dropdown that collapsed to the entry already chosen
        would leave no way back out of it."""
        current = view.filters.feature_id
        total = sum(option.total for option in view.features)
        options = [
            ("", f"feature · all {total}", current is None),
            *(
                (
                    str(option.feature_id),
                    f"feature · {option.feature_key} {option.total}",
                    option.feature_id == current,
                )
                for option in view.features
            ),
        ]
        text = next(option_text for _, option_text, on in options if on)
        self._dropdown(
            name="feature",
            text=text,
            aria_label="Feature",
            options=options,
            on_pick=self._pick_feature,
        )

    def _tag_chip(self) -> None:
        """The six-option tag filter: three states, then the three tags."""
        current = mismatches_state().tag_state
        text = next(
            (label for value, label in TAG_FILTER_OPTIONS if value == current),
            TAG_FILTER_OPTIONS[0][1],
        )
        self._dropdown(
            name="tag",
            text=text,
            aria_label="Tag",
            options=[(value, label, value == current) for value, label in TAG_FILTER_OPTIONS],
            on_pick=self._pick_tag,
        )

    def _scored_at(self, view: MismatchListView) -> None:
        """`SD25`, §17.7 — the run's `finished_at`, beside the run label.

        A re-score deletes rows that no longer mismatch, tags included, so a
        tally can move under an analyst and nothing guards that. What the view
        owes instead is a **visible reason for a list that changed**, and this
        is the closest honest thing RA2 records: a re-score does not restamp
        it, and §17.7 says why no `scored_at` column was added to make it.

        Not inside `chrome.run_descriptor`: that helper renders a
        `RunDescriptorView`, which carries no timestamp, and it belongs to the
        Results package.
        """
        finished = view.run_finished_at
        label = EMPTY_CELL if finished is None else finished.strftime("%Y-%m-%d %H:%M")
        readout = (
            ui.element("span")
            .classes("mono")
            .props('data-testid="run-finished-at"')
            .mark("run-finished-at")
            .style("font-size:11px;color:var(--ink3);white-space:nowrap;")
        )
        with readout:
            ui.label(f"run finished {label}")

    def _dropdown(
        self,
        *,
        name: str,
        text: str,
        aria_label: str,
        options: Sequence[tuple[str, str, bool]],
        on_pick: Callable[[str], Awaitable[None]],
    ) -> None:
        """One dropdown chip and, when open, its panel — the Census toolbar's
        own component, reused unchanged (§3.2: assembled, never invented)."""
        expanded = self._open_menu == name
        with ui.element("div").style("position:relative;display:inline-flex;"):
            chip(text, label=aria_label, on_click=lambda: self._toggle_menu(name)).props(
                f'data-chip="{name}" aria-haspopup="listbox" '
                f'aria-expanded="{"true" if expanded else "false"}"'
            ).mark("chip", f"chip-{name}")
            if not expanded:
                return
            with data_props(
                ui.element("div")
                .props(f'role="listbox" data-testid="menu-{name}"')
                .style(_MENU_STYLE),
                {"aria-label": aria_label},
            ):
                for value, option_text, selected in options:
                    button = data_props(
                        ui.element("button")
                        .classes("mono")
                        .props(
                            'type="button" role="option" '
                            f'aria-selected="{"true" if selected else "false"}" '
                            f'data-testid="option-{name}"'
                        )
                        .mark(f"option-{name}")
                        .style(_MENU_ITEM_STYLE + (_MENU_ITEM_ON_STYLE if selected else "")),
                        #: The value as well as the menu, so a test — and a
                        #: deep link a person pastes — can name the option it
                        #: means rather than the first one drawn.
                        {"aria-label": option_text, "data-option": value},
                    )
                    button.on("click", cast("Callable[[], None]", lambda v=value: on_pick(v)))
                    with button:
                        ui.label(option_text)

    def _export_button(self) -> None:
        """ ".btn" secondary — the Census toolbar's own button."""
        button = (
            ui.element("button")
            .classes("btn secondary")
            .props('type="button" data-testid="export-csv"')
            .mark("export-csv")
        )
        button.on("click", cast("Callable[[], None]", self._export))
        with button:
            ui.label(EXPORT_LABEL)

    # --- the table ----------------------------------------------------------

    def _table_card(self, view: MismatchListView) -> None:
        state = _state()
        with card(flex="1", extra="min-height:0;overflow:hidden;"):
            with ui.element("div").style("flex:1;min-height:0;overflow:auto;"):
                data_table(
                    columns=self._columns(),
                    rows=view.rows.items,
                    state=state,
                    on_sort=_sync(self._sort),
                    empty_message=NO_MATCHES_MESSAGE,
                    wide=True,
                    testid="table-mismatches",
                )
            pagination_row(
                state=state,
                total=view.rows.total,
                shown=len(view.rows.items),
                on_page=_sync(self._page),
                on_page_size=_sync(self._page_size),
            )

    def _columns(self) -> tuple[ColumnSpec[MismatchRowView], ...]:
        """§3.2's seven columns, widths verbatim.

        Four are sortable — feature, record, tag, reviewed — and there is no
        fifth (`MISMATCH_SORT_KEYS`, C3). **Nothing sorts by "how wrong"**:
        there is no such number, and inventing one is §16.9's clustering /
        agreement / sampling deferral arriving as a helpful-looking feature.

        There is no Model column: the list is one run at a time and the
        toolbar names it (`SD26`, §17.6).

        **Two widths differ from §3.2's table, and the total does not.** The
        three-way tag control renders 290px wide at the kit's own segment
        padding, in a column §3.2 allots 210 — so it overflowed, and the
        Reviewed cell beside it intercepted every click on the clear. J14 is
        what found that; no layer below a browser could. The 60px comes back
        from the two value columns, which hold enum codes and had it to spare,
        so the fixed total is unchanged at 956px (`P5-D5`).
        """
        return (
            ColumnSpec(
                key="feature",
                label="Feature",
                width="180px",
                sortable=True,
                cell_class="mono",
                render=lambda row: (
                    ui.label(row.feature_key)
                    .props('data-testid="mismatch-feature"')
                    .mark("mismatch-feature")
                    .style("font-size:11.5px;")
                ),
            ),
            ColumnSpec(
                key="record",
                label="Record",
                width="190px",
                sortable=True,
                cell_class="mono",
                render=_render_record,
            ),
            ColumnSpec(
                key="record_value",
                label="Record value",
                width="110px",
                cell_class="mono td-clip",
                render=lambda row: _value_label(row.record_value, "mismatch-record-value"),
            ),
            ColumnSpec(
                key="extracted_value",
                label="Extracted value",
                width="110px",
                cell_class="mono td-clip",
                render=lambda row: _value_label(row.extracted_value, "mismatch-extracted-value"),
            ),
            ColumnSpec(
                key="evidence_span",
                label="Evidence span",
                cell_class="td-wrap",
                render=_render_span,
            ),
            ColumnSpec(
                key="tag",
                label="Tag",
                width="270px",
                sortable=True,
                render=self._render_tag,
            ),
            ColumnSpec(
                key="reviewed",
                label="Reviewed",
                width="96px",
                sortable=True,
                cell_class="mono",
                render=_render_reviewed,
            ),
        )

    def _render_tag(self, row: MismatchRowView) -> None:
        """The inline three-way control plus a clear (Q2, `P3-D22`).

        In the row, not behind a panel: the judgement is made **while
        scanning**, and §12's own example — "of 40 reviewed" — describes bulk
        review, not forty modal round trips.

        A stored value `MismatchTag` does not name renders **as itself**, in a
        chip beside the control rather than as a fourth segment: nothing in the
        MVP writes one, and offering it as a value would make it writable
        (`SD24`, §17.5).
        """
        if row.is_other:
            other = (
                ui.element("span")
                .classes("chip")
                .props('data-testid="other-tag"')
                .mark("other-tag")
            )
            with other:
                ui.label(row.analyst_tag or "")
        control = segmented_control(
            options=[TAG_LABELS[tag] for tag in MismatchTag],
            value=None if row.tag is None else TAG_LABELS[row.tag],
            label=f"Tag {row.feature_key} {row.record_id}",
            on_change=cast(
                "Callable[[str], None]",
                lambda label, mid=str(row.mismatch_id): self._tag(mid, label),
            ),
            on_clear=cast(
                "Callable[[], None]",
                lambda mid=str(row.mismatch_id): self._clear(mid),
            ),
            clear_label=CLEAR_LABEL,
        )
        #: The kit's 12px segment padding renders these three words 290px wide
        #: — 80 more than the column has. `.seg-tight` is 7px, which brings it
        #: to ~260 and leaves the words intact; shortening them is not
        #: available, because §12's own tally prints them (C4).
        control.classes("seg-tight")

    # --- the tally strip ----------------------------------------------------

    def _tally_strip(self, tallies: Sequence[ReviewTallyView]) -> None:
        """mvp-spec.md §12's output: "a tally per feature".

        Scoped to the **current filter**, like the rows above it — one filter
        shape reaches both reads, so the strip and the table cannot disagree
        (§17.4).
        """
        for entry in tallies:
            with (
                data_props(
                    card(flex="1", extra="padding:0;min-width:220px;").props('data-card="tally"'),
                    {"data-feature": entry.feature_id},
                ),
                card_header(title=entry.feature_key, count=f"{entry.tally.total} mismatches"),
            ):
                pass
            with ui.element("div").style("padding:10px 14px;"):
                data_props(
                    ui.label(tally_sentence(entry.tally))
                    .props('data-testid="tally-sentence"')
                    .mark("tally-sentence")
                    .style("font-size:12.5px;color:var(--ink2);"),
                    {"data-feature": entry.feature_id},
                )

    # --- handlers -----------------------------------------------------------
    #
    # Async, and they await `reload` directly. Deferring through
    # `ui.timer(0, ...)` schedules the redraw outside the event's own round
    # trip, so the browser acknowledges the click before the new markup
    # exists — which reads as a dead control under Playwright and as a flicker
    # to a person (the lesson `ui/views/results/__init__.py` records).

    async def _tag(self, mismatch_id: str, label: str) -> None:
        tag = next((t for t in MismatchTag if TAG_LABELS[t] == label), None)
        if tag is None:  # pragma: no cover - the control offers only these three
            return
        await self._services.mismatch.tag(MismatchId(mismatch_id), tag=tag)
        await self.reload()

    async def _clear(self, mismatch_id: str) -> None:
        await self._services.mismatch.clear_tag(MismatchId(mismatch_id))
        await self.reload()

    async def _sort(self, key: str) -> None:
        set_table_state(MISMATCH_TABLE, _state().toggled(key))
        self._open_menu = None
        await self.reload()

    async def _page(self, page: int) -> None:
        current = _state()
        set_table_state(
            MISMATCH_TABLE, TableState(current.sort_key, current.sort_dir, page, current.page_size)
        )
        await self.reload()

    async def _page_size(self, size: int) -> None:
        current = _state()
        set_table_state(MISMATCH_TABLE, TableState(current.sort_key, current.sort_dir, 1, size))
        await self.reload()

    async def _pick_run(self, run_id: str) -> None:
        state = mismatches_state()
        state.run_id = run_id
        set_mismatches_state(state)
        await self._refilter()

    async def _pick_feature(self, feature_id: str) -> None:
        state = mismatches_state()
        state.feature_id = feature_id
        set_mismatches_state(state)
        await self._refilter()

    async def _pick_tag(self, tag_state: str) -> None:
        state = mismatches_state()
        state.tag_state = tag_state
        set_mismatches_state(state)
        await self._refilter()

    async def _refilter(self) -> None:
        """Changing any filter refilters and **resets to page 1** — the same
        rule Census and Import follow. The service is told the page; it never
        remembers one."""
        _reset_page()
        self._open_menu = None
        await self.reload()

    def _toggle_menu(self, name: str) -> None:
        self._open_menu = None if self._open_menu == name else name
        self._render()

    async def _export(self) -> None:
        """The **currently filtered, currently sorted** rows (§7, `P4-D3`).

        `export_rows` is asked for the whole filtered set rather than the page
        on screen, because an export has no paging of its own — and it is the
        same call with the same filters, so the file cannot disagree with the
        table it came from. The bytes are the service's.
        """
        state = mismatches_state()
        if not state.evaluation_id:
            return
        evaluation_id = EvaluationId(state.evaluation_id)
        table = _state()
        rows = await self._services.mismatch.export_rows(
            evaluation_id,
            run_id=RunId(state.run_id) if state.run_id else None,
            feature_id=FeatureId(state.feature_id) if state.feature_id else None,
            tag_state=_tag_filter(state.tag_state),
            sort_key=table.sort_key,
            sort_dir=table.sort_dir,
        )
        data = self._services.export.mismatches_csv(
            rows.rows.items,
            evaluation_id=evaluation_id,
            run_label=rows.run_label,
            filter_label=_filter_label(rows),
        )
        ui.download.content(data, f"mismatches-{state.evaluation_id}.csv", media_type="text/csv")


# --- cell renderers -----------------------------------------------------------


def _render_record(row: MismatchRowView) -> None:
    """The record id, truncated, plus **the anonymisation chip**.

    `mvp-spec.md` §13 requires the per-record marking "everywhere text is
    shown", and this row shows an evidence span — so the chip belongs on every
    row that carries one, not on a detail view somebody has to open.
    """
    ui.label(str(row.record_id)[:RECORD_ID_CHARS]).props('data-testid="mismatch-record"').mark(
        "mismatch-record"
    ).style("font-size:11.5px;")
    if row.anonymised:
        marker = (
            ui.element("span")
            .classes("chip")
            .props('data-testid="anonymised-chip"')
            .mark("anonymised-chip")
        )
        with marker:
            ui.label("anonymised")


def _value_label(value: str | None, testid: str) -> None:
    ui.label(value if value else EMPTY_CELL).props(f'data-testid="{testid}"').mark(testid).style(
        "font-size:11.5px;"
    )


def _render_span(row: MismatchRowView) -> None:
    """The evidence span, wrapped and capped at three lines by `.td-wrap` (Q6).

    `mvp-spec.md` §19's criterion 7 names this field explicitly, so it is shown
    in the table: one line would hide the thing the criterion asks for, and a
    hover reveal would put it out of reach of a keyboard and a screen reader.
    The full value is in the export.
    """
    ui.label(row.evidence_span or EMPTY_CELL).props('data-testid="mismatch-span"').mark(
        "mismatch-span"
    ).style("font-size:12.5px;color:var(--ink2);")


def _render_reviewed(row: MismatchRowView) -> None:
    stamped = row.tagged_at
    ui.label(EMPTY_CELL if stamped is None else stamped.strftime("%Y-%m-%d")).props(
        'data-testid="mismatch-reviewed"'
    ).mark("mismatch-reviewed").style("font-size:11.5px;color:var(--ink3);")


# --- helpers ------------------------------------------------------------------


def _state() -> TableState:
    """This client's mismatch `TableState`, Feature ▲ on first use."""
    return table_state(
        MISMATCH_TABLE,
        sort_key=DEFAULT_SORT_KEY,
        sort_dir=DEFAULT_SORT_DIR,
        page_size=PAGE_SIZE,
    )


def _reset_page() -> None:
    current = _state()
    set_table_state(
        MISMATCH_TABLE, TableState(current.sort_key, current.sort_dir, 1, current.page_size)
    )


def _is_filtered() -> bool:
    """Whether anything narrows the run's own list.

    The distinction the two empty states turn on: "no mismatches in this run"
    is a fact about the run and a **good** one; "none match this filter" is a
    fact about the filter. The run itself is not a filter — there is no
    unfiltered state that spans runs (`SD26`).
    """
    state = mismatches_state()
    return bool(state.feature_id) or state.tag_state != TagState.ANY.value


def _tag_filter(stored: str) -> TagFilter:
    """The stored string as the closed field the service takes.

    `TagState` and `MismatchTag` have disjoint values, so one string carries
    either and this is the one place it is widened back. An unrecognised value
    — a hand-edited URL, a storage payload from an older build — falls back to
    `any` rather than raising: a filter is a rendering input, and the honest
    answer to "show me a tag that does not exist" is the unfiltered list.
    """
    for state in TagState:
        if state.value == stored:
            return state
    for tag in MismatchTag:
        if tag.value == stored:
            return tag
    return TagState.ANY


def _filter_label(view: MismatchListView) -> str:
    """What the CSV's comment line says this file is a list of."""
    parts = [f"tag {view.filters.tag_state}"]
    if view.filters.feature_id is not None:
        feature = next(
            (o.feature_key for o in view.features if o.feature_id == view.filters.feature_id),
            str(view.filters.feature_id),
        )
        parts.append(f"feature {feature}")
    return " · ".join(parts)


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to the component kit's synchronous callback type.

    NiceGUI's `handle_event` awaits an awaitable result inside the sender's
    slot context, so this is a typing formality and not a change of behaviour.
    """
    return cast("Callable[P, None]", action)
