# STUB — bodies owned by V1 (feat/p4-results-extraction, phase 4 Wave 4).
"""Results — one route, three tabs (design/results/README.md).

**The first view in the repo that is a package rather than a module**
(`SD22`). Three tabs of one screen get built by three agents in one wave;
three files is what makes that parallel, and a single `results_view.py` would
serialise the wave for no architectural gain. The route, the shell and the tab
strip live here and belong to V1; the tab bodies belong to V1, V2 and V3.

`design/results/README.md` is explicit that on this view **the copy is the
design**: "the suppression notices, the caveat panels and the tie language are
the product's honesty guarantees, not decoration. Reproduce them verbatim
unless the team changes the statistics." Every one of them is asserted verbatim
at the UI layer.

**The evaluation picker the design does not draw.** The boards render one run
descriptor and no way to choose it. `/results?evaluation=<id>`, with the
standard empty card listing launched evaluations when the parameter is absent
or unknown (plan-phase-4.md C7) — and phase 3's Evaluation view left its
runs-table run-id link pointing at a deliberate placeholder route, which is the
link that lands here.

**The header carries `NavItem.description`, not the design's board subtitle.**
The board says "Extraction and presence scores for one evaluation."; `NAV_ITEMS`
says "Per-feature, per-model precision, recall and F1, with intervals." Every
view in this app feeds the header from its nav item, and
`tests/ui/test_shell_nav.py` asserts that for all eight — so matching the board
here would mean editing `shell.py` beyond the one `built` flag §6.1 permits V1.
Left as an open point for a later design round rather than taken silently.

**Four** states that must not share a rendering (§16.7 named three):
**not scored yet**, **scoring…**, **nothing scoreable** — which says *which*,
because "no results" and "not enough data for results" are different facts —
and **scoring did not finish**, added here because the first and the last
shared a sentence. A finished run with no `score` rows was told "Not scored
yet. Scoring starts automatically when a run completes", which is a promise
about the next few seconds; a pass that crashed wears that sentence for as
long as the tab stays open, and the control it names did not exist.

The page **polls** while a run or a pass is still moving, which is what the
"scoring…" copy has always claimed and what nothing in this file did.

The usual rules: no business logic (Do-NOT #7) — every number, interval, mark
and suppression decision arrives already made from `ResultsService` and
`RankingService`; no module-level mutable state (Do-NOT #8) — the active tab,
the expanded feature, the page and the sort live in `app.storage.client`.

**M27 freezes the signature. V1 writes the body.**
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.domain.ids import EvaluationId, RunId
from ra2.services.container import Services
from ra2.services.errors import NotFoundError, RunNotScoreableError
from ra2.services.readmodels import EvaluationDraftView, ScoringStatusView, SortDir
from ra2.ui.shell import item_for_key, shell
from ra2.ui.state import ResultsState, results_state, set_results_state
from ra2.ui.views.results.chrome import empty_card
from ra2.ui.views.results.extraction_tab import render_extraction_tab
from ra2.ui.views.results.presence_tab import render_presence_tab
from ra2.ui.views.results.ranking_tab import render_ranking_tab
from ra2.ui.views.scoring_states import (
    INCOMPLETE_BODY,
    INCOMPLETE_TITLE,
    NOT_SCORED_BODY,
    NOT_SCORED_TITLE,
    NOTHING_SCOREABLE_BODY,
    NOTHING_SCOREABLE_TITLE,
    PARTIAL_NOTE,
    POLL_FAST_S,
    POLL_SLOW_S,
    RESCORE_STARTED,
    SCORING_BODY,
    SCORING_TITLE,
    STALLED_BODY,
    STALLED_TITLE,
    rescore_row,
    run_label,
)

#: The scoring sentences are **re-exported deliberately**: they live in
#: `views/scoring_states.py` so Mismatches says the same things, and every
#: existing reader — tests included — imports them from here.
__all__ = [
    "INCOMPLETE_BODY",
    "INCOMPLETE_TITLE",
    "NOTHING_SCOREABLE_BODY",
    "NOTHING_SCOREABLE_TITLE",
    "NOT_SCORED_BODY",
    "NOT_SCORED_TITLE",
    "PARTIAL_NOTE",
    "POLL_FAST_S",
    "POLL_SLOW_S",
    "RESCORE_STARTED",
    "SCORING_BODY",
    "SCORING_TITLE",
    "STALLED_BODY",
    "STALLED_TITLE",
    "TABS",
    "register",
]

_ITEM: Final = item_for_key("results")

#: The three tabs, in the design's order. One route, one sidebar entry.
TABS: Final = (
    ("extraction", "Goal 1 — Extraction"),
    ("presence", "Goal 2 — Presence"),
    ("ranking", "Ranking"),
)

EMPTY_TITLE = "No evaluation selected."
EMPTY_BODY = (
    "Results are read for one evaluation at a time. Pick a launched evaluation "
    "below, or follow a run from the Evaluation view."
)
#: The same card when there is genuinely nothing to list. The sentence above
#: would be pointing at an empty space again, which is the defect this state
#: exists to stop.
EMPTY_BODY_NONE = (
    "Results are read for one evaluation at a time, and no evaluation has been "
    "launched yet. Set one up on the Evaluation view and launch it."
)
#: **The four scoring sentences now live in `views/scoring_states.py`** and are
#: re-exported here, because Mismatches says the same things about the same
#: runs and two copies of a sentence are two sentences waiting to drift
#: (`plan-scoring-visibility-follow-ups.md` Part 1). Tests and any other
#: reader keep importing them from this module.

#: How many runs one evaluation's ordinals are read from — `evaluation_view`'s
#: `RUNS_SUMMARY_CAP`, for its reason: the ordinal is a property of the whole
#: set, so it cannot be taken from a page of it.
_RUNS_CAP: Final = 200


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page(evaluation: str = "", run: str = "", tab: str = "") -> None:
        """`?evaluation=<id>` — and **`?run=<id>`**, which is what links here.

        The Evaluation view's runs table has linked each row to
        `/results?run=<run id>` since phase 3, and this page understood only
        `?evaluation=`. FastAPI drops an undeclared query parameter without a
        word, so the one control in the product that takes an analyst from a
        finished run to its board landed on **"No evaluation selected."** —
        the picker, which lists the evaluation they had just come from.

        Accepted here rather than rewritten there, because a link that names
        the run is the right link: it says which board, and it is the id in
        every log line about that run.
        """
        page = _ResultsPage(services)
        await page.build(evaluation=evaluation, run=run, tab=tab)


class _ResultsPage:
    """One client's Results view — three tabs, one route.

    **The picker the design does not draw.** The boards render one run
    descriptor and no way to choose it. `/results?evaluation=<id>` names one;
    without it the view lists the launched evaluations, which is also where
    phase 3's Evaluation view sends its runs-table link (plan-phase-4.md C7).

    No business logic (Do-NOT #7): every number, interval, mark and suppression
    decision arrives already made. This file decides only which tab is drawn
    and which row is expanded. No module-level state (Do-NOT #8): all of it is
    in `app.storage.client` through `ResultsState`.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._state: ResultsState | None = None
        self._body: Element | None = None
        self._root: Element | None = None
        self._poll: ui.timer | None = None
        #: The statuses the current render was drawn from — what the poll
        #: compares against to decide whether it still has anything to wait
        #: for, and what the Re-score control reads the run id from.
        self._statuses: tuple[ScoringStatusView, ...] = ()
        #: Whether the one extra read a stalled page is allowed has been
        #: spent (`_start_polling`).
        self._stalled_recheck = False

    async def build(self, *, evaluation: str, run: str = "", tab: str = "") -> None:
        if run and not evaluation:
            # A run id names its evaluation, and one read resolves it. A
            # missing run falls through to the picker rather than raising:
            # this is a URL somebody followed, and the picker is the page
            # that can say "pick another one".
            try:
                evaluation = str((await self._services.run.get(RunId(run))).evaluation_id)
            except NotFoundError:
                evaluation = ""
        state = results_state()
        if evaluation:
            # A URL naming a different evaluation resets what was open: an
            # expanded row from another run would point at a feature this one
            # may not have.
            if evaluation != state.evaluation_id:
                state = ResultsState(tab=state.tab, evaluation_id=evaluation)
            else:
                state.evaluation_id = evaluation
        if tab and tab in {key for key, _ in TABS}:
            state.tab = tab
        set_results_state(state)
        self._state = state

        data_dir_view = self._services.lifecycle.data_dir()
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            data_dir=data_dir_view.data_dir,
            database_replaced=data_dir_view.database_replaced,
            content_padding="0",
            content_gap="0",
        ):
            self._root = ui.element("div").style(
                "display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;"
            )
            with self._root:
                self._body = ui.element("div").style(
                    "display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;"
                )
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything and redraw. One place reads, so no handler has
        to work out which half of the page its action invalidated."""
        assert self._body is not None and self._state is not None
        self._body.clear()
        state = self._state

        if not state.evaluation_id:
            with self._body:
                await self._render_picker()
            return

        evaluation_id = EvaluationId(state.evaluation_id)
        try:
            statuses = await self._services.results.scoring_status(evaluation_id)
        except NotFoundError:
            with self._body:
                await self._render_picker(missing=state.evaluation_id)
            return
        self._statuses = statuses
        #: The runs a Re-score would help: a pass that wrote nothing, and one
        #: that wrote some of it. Never a run still in flight — `submit_rescore`
        #: refuses that, and offering it would be a button that 409s.
        unscored = [s for s in statuses if s.scoring_stalled or s.scoring_incomplete]

        with self._body:
            self._render_tab_strip()
            content = ui.element("div").style(
                "flex:1;min-height:0;min-width:0;display:flex;flex-direction:column;"
            )
        with content:
            # **Four** states that must not share a rendering (§16.7 plus
            # `STALLED_TITLE`). Each says *which*: "no results", "not enough
            # data for results", "not yet" and "it stopped" are four different
            # facts about the run, and the last two shared a sentence.
            if statuses and not any(s.is_scoreable for s in statuses):
                empty_card(NOTHING_SCOREABLE_TITLE, NOTHING_SCOREABLE_BODY)
            elif any(s.running for s in statuses):
                empty_card(SCORING_TITLE, SCORING_BODY)
            elif not any(s.is_scored for s in statuses):
                # Three different facts, not one. A run that has not finished
                # is waiting; a finished run with no rows did not run its
                # pass; a finished run with *some* rows stopped part-way. The
                # first is patience, the other two are a button.
                if not all(s.is_finished for s in statuses):
                    empty_card(NOT_SCORED_TITLE, NOT_SCORED_BODY)
                elif any(s.scoring_stalled for s in statuses):
                    empty_card(STALLED_TITLE, STALLED_BODY)
                else:
                    empty_card(INCOMPLETE_TITLE, INCOMPLETE_BODY)
                await self._render_rescore(unscored)
            else:
                # **Also when the boards render.** An evaluation runs several
                # models and each is scored by its own pass, so one model's
                # pass can fail while the others succeed — and then the board
                # draws a column of blanks for it, which reads as a model that
                # answered nothing rather than one nobody scored. The strip
                # says which, and offers the same control.
                await self._render_rescore(unscored, note=PARTIAL_NOTE)
                await self._render_active_tab(evaluation_id)
        self._start_polling()

    async def _render_rescore(
        self, unscored: Sequence[ScoringStatusView], *, note: str | None = None
    ) -> None:
        """The control the empty card has named since phase 4, from
        `scoring_states.rescore_row` so that Mismatches offers the same one.

        The ordinals are this view's to fetch — `RunView.ordinal` is computed
        once over the whole set, precisely so no view works it out from the
        rows it happens to be holding — and the markup is shared.
        """
        if not unscored:
            return
        ordinals = await self._ordinals()
        rescore_row(
            [(status.run_id, ordinals.get(status.run_id, 0)) for status in unscored],
            on_rescore=self._rescore,
            note=note,
        )

    async def _ordinals(self) -> dict[RunId, int]:
        """`run_id -> ordinal`, from the service that owns the numbering.

        `RunView.ordinal` is computed once, over the whole set, precisely so
        no view has to work it out from the rows it happens to be holding.
        """
        assert self._state is not None
        page = await self._services.run.list_runs(
            EvaluationId(self._state.evaluation_id), page=1, page_size=_RUNS_CAP
        )
        return {run.run_id: run.ordinal for run in page.items}

    async def _rescore(self, run_id: RunId, ordinal: int) -> None:
        """Submit the pass and redraw. **Submitted, never awaited**: the
        request returns a task id and the poll below is what watches it, the
        same handshake import and runs use (§9)."""
        try:
            await self._services.scoring.submit_rescore(run_id)
        except (NotFoundError, RunNotScoreableError) as error:
            # The run changed under the page — discarded, or resumed and no
            # longer `done`. A redraw is the answer; the notification says
            # why the screen is about to look different.
            ui.notify(str(error))
            await self.reload()
            return
        ui.notify(RESCORE_STARTED.format(run=run_label(ordinal)))
        await self.reload()

    # --- the poll ----------------------------------------------------------

    def _start_polling(self) -> None:
        """Re-read while anything is still expected to move, then stop.

        `evaluation_view._start_polling`'s shape, and the gap it closes is the
        reported one: this page had **no timer at all** while its own copy
        said *"Progress is polled; this page refreshes itself."* A Results
        page opened during a run rendered "Not scored yet" and kept rendering
        it after the pass had finished, for as long as the tab stayed open.

        **Not unconditional**, unlike `evaluation_view`'s: a settled page here
        is waiting for a *click*, not for time, and a timer on a scored board
        would re-read the whole status set for as long as the tab is open for
        nothing.

        The one exception is the stalled state, which gets **one** more tick
        (`_stalled_recheck`). `run_service._chain_scoring` re-reads the run
        row between writing `done` and calling `submit`, so a page that loads
        inside that gap sees a finished run, no rows and nothing in flight —
        and would say "scoring did not finish" about a pass that is a
        heartbeat from starting. That is precisely the misdiagnosis this whole
        change exists to remove, so it is worth one read to avoid making it
        from the other direction.
        """
        if self._root is None:
            return
        if self._settled:
            if self._poll is not None:
                self._poll.deactivate()
                self._poll = None
            return
        if self._poll is not None:
            # Already running: only the interval can have changed, and
            # `ui.timer` re-reads it before each sleep — so this takes effect
            # on the next tick without tearing the timer down.
            self._poll.interval = self._interval
            return

        async def poll() -> None:
            await self.reload()
            if self._poll is not None:
                if self._settled:
                    self._poll.deactivate()
                    self._poll = None
                else:
                    self._poll.interval = self._interval

        with self._root:
            self._poll = ui.timer(self._interval, poll)

    @property
    def _interval(self) -> float:
        """Fast for a pass, slow for a run — see `POLL_FAST_S`."""
        return POLL_FAST_S if any(s.running for s in self._statuses) else POLL_SLOW_S

    @property
    def _settled(self) -> bool:
        """Whether anything on this page is still expected to change.

        A scoring pass in flight, or a run that has not finished — that run's
        own terminal `done` is what submits the pass (`SD17`), so a page
        watching a running run is waiting for two things in sequence. Plus
        the single stalled re-check `_start_polling` explains.
        """
        if any(s.running or not s.is_finished for s in self._statuses):
            return False
        if any(s.scoring_stalled for s in self._statuses) and not self._stalled_recheck:
            self._stalled_recheck = True
            return False
        return True

    async def _render_active_tab(self, evaluation_id: EvaluationId) -> None:
        assert self._state is not None
        state = self._state
        if state.tab == "presence":
            presence = await self._services.results.presence_tab(
                evaluation_id,
                model_id=state.presence_model_id or None,
                feature_key=state.presence_feature_key or None,
            )
            render_presence_tab(view=presence, on_select_model=self._select_model)
        elif state.tab == "ranking":
            render_ranking_tab(view=await self._services.ranking.ranking_tab(evaluation_id))
        else:
            extraction = await self._services.results.extraction_tab(
                evaluation_id,
                expanded_feature_id=(
                    None if state.expanded_feature_id is None else state.expanded_feature_id  # type: ignore[arg-type]
                ),
                page=1,
                page_size=10,
                sort_key="name",
                sort_dir=SortDir.ASC,
            )
            render_extraction_tab(view=extraction, on_toggle_feature=self._toggle_feature)

    # --- handlers ----------------------------------------------------------

    # Handlers are **async and await `reload` directly**. Deferring through
    # `ui.timer(0, ...)` schedules the redraw outside the event's own round
    # trip, so the browser acknowledges the click before the new markup
    # exists — which reads as a dead control under Playwright and as a
    # flicker to a person.

    async def _toggle_feature(self, feature_id: str) -> None:
        """**One breakdown open at a time** — clicking the open row closes it."""
        assert self._state is not None
        self._state.expanded_feature_id = (
            None if self._state.expanded_feature_id == feature_id else feature_id
        )
        set_results_state(self._state)
        await self.reload()

    async def _select_model(self, model_id: str) -> None:
        assert self._state is not None
        self._state.presence_model_id = model_id
        set_results_state(self._state)
        await self.reload()

    async def _switch_tab(self, key: str) -> None:
        assert self._state is not None
        self._state.tab = key
        set_results_state(self._state)
        await self.reload()

    # --- chrome ------------------------------------------------------------

    def _render_tab_strip(self) -> None:
        assert self._state is not None
        strip = (
            ui.element("div")
            .props('data-testid="results-tabs"')
            .mark("results-tabs")
            .style(
                "flex:none;display:flex;align-items:center;gap:10px;padding:11px 28px;"
                "background:var(--surface);border-bottom:1px solid var(--rule);"
            )
        )
        with (
            strip,
            ui.element("div").style(
                "display:flex;gap:22px;align-self:stretch;align-items:flex-end;margin-bottom:-11px;"
            ),
        ):
            for key, label in TABS:
                active = key == self._state.tab
                button = (
                    ui.element("button")
                    .classes(f"tab{' on' if active else ''}")
                    .props(
                        f'type="button" data-testid="results-tab" data-tab="{key}" '
                        f'aria-current="{"page" if active else "false"}"'
                    )
                    .mark("results-tab")
                    .on("click", lambda _event, key=key: self._switch_tab(key))
                )
                with button:
                    ui.label(label)

    async def _render_picker(self, *, missing: str = "") -> None:
        """The index the design does not draw (C7) — **with the list in it**.

        This rendered the card and nothing else, under copy reading *"Pick a
        launched evaluation below"*. There was nothing below. Every route
        into this view that does not carry an id — the sidebar's own Results
        entry, most of all — therefore ended on a sentence pointing at an
        empty space, which is the same defect as an empty state naming a
        control that does not exist, one screen further out.

        Launched evaluations only, newest first: an unlaunched draft has no
        runs, so it has no board, and offering it would be a link to another
        empty state.
        """
        drafts = [d for d in await self._services.evaluation.list_evaluations() if d.is_launched]
        with ui.element("div").style(
            "padding:18px 28px;display:flex;flex-direction:column;gap:12px;"
        ):
            empty_card(
                EMPTY_TITLE if not missing else f"No evaluation {missing}.",
                EMPTY_BODY if drafts else EMPTY_BODY_NONE,
            )
            if drafts:
                self._picker_list(drafts)

    def _picker_list(self, drafts: Sequence[EvaluationDraftView]) -> None:
        """One row per launched evaluation: its name, when it was launched,
        and the models it ran. Enough to tell two apart, which is all this
        has to do — the board itself carries the full identity line."""
        with (
            ui.element("div")
            .classes("card")
            .props('data-testid="evaluation-picker"')
            .mark("evaluation-picker")
            .style("display:flex;flex-direction:column;")
        ):
            for index, draft in enumerate(drafts):
                border = "" if index == 0 else "border-top:1px solid var(--rule);"
                with ui.element("div").style(
                    f"{border}padding:11px 16px;display:flex;align-items:baseline;"
                    "gap:12px;min-width:0;"
                ):
                    link = ui.link(
                        text=draft.name or str(draft.evaluation_id),
                        target=f"/results?evaluation={draft.evaluation_id}",
                    )
                    link.classes(remove="nicegui-link", add="mono")
                    link.props('data-testid="picker-evaluation"').mark("picker-evaluation")
                    link.style("font-size:12.5px;color:var(--ink);")
                    ui.label(_launched_label(draft.launched_at)).classes("mono ink3").props(
                        'data-testid="picker-launched"'
                    ).style("font-size:11px;")
                    if draft.selected_models:
                        ui.label(" · ".join(draft.selected_models)).classes("mono ink3").props(
                            'data-testid="picker-models"'
                        ).style(
                            "font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                        )


def _launched_label(launched_at: datetime | None) -> str:
    """`dd.mm.yy - hh:mm:ss`, the timestamp format the runs table already
    uses (`evaluation_view.TIMESTAMP_FORMAT`). `None` cannot happen on a
    launched evaluation, and says so rather than rendering an empty cell."""
    return "—" if launched_at is None else launched_at.strftime("%d.%m.%y - %H:%M:%S")
