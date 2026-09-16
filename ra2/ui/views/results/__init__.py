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

Three states that must not share a rendering (§16.7): **not scored yet**,
**scoring…** (polled through `GET /api/v1/tasks/{id}` exactly as import and
runs are), and **nothing scoreable** — the last one says *which*, because
"no results" and "not enough data for results" are different facts.

The usual rules: no business logic (Do-NOT #7) — every number, interval, mark
and suppression decision arrives already made from `ResultsService` and
`RankingService`; no module-level mutable state (Do-NOT #8) — the active tab,
the expanded feature, the page and the sort live in `app.storage.client`.

**M27 freezes the signature. V1 writes the body.**
"""

from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.domain.ids import EvaluationId
from ra2.services.container import Services
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import SortDir
from ra2.ui.shell import item_for_key, shell
from ra2.ui.state import ResultsState, results_state, set_results_state
from ra2.ui.views.results.chrome import empty_card
from ra2.ui.views.results.extraction_tab import render_extraction_tab
from ra2.ui.views.results.presence_tab import render_presence_tab
from ra2.ui.views.results.ranking_tab import render_ranking_tab

__all__ = ["TABS", "register"]

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
NOT_SCORED_TITLE = "Not scored yet."
NOT_SCORED_BODY = (
    "This run finished but has not been scored. Scoring starts automatically "
    "when a run completes; use Re-score if you need to run it again."
)
SCORING_TITLE = "Scoring…"
NOTHING_SCOREABLE_TITLE = "Nothing in this run could be scored."


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page(evaluation: str = "", tab: str = "") -> None:
        page = _ResultsPage(services)
        await page.build(evaluation=evaluation, tab=tab)


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

    async def build(self, *, evaluation: str, tab: str) -> None:
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

        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            data_dir=self._services.lifecycle.data_dir().data_dir,
            content_padding="0",
            content_gap="0",
        ):
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

        with self._body:
            self._render_tab_strip()
            content = ui.element("div").style(
                "flex:1;min-height:0;min-width:0;display:flex;flex-direction:column;"
            )
        with content:
            # Three states that must not share a rendering (§16.7). The third
            # says *which*, because "no results" and "not enough data for
            # results" are different facts about the run.
            if statuses and not any(s.is_scoreable for s in statuses):
                empty_card(NOTHING_SCOREABLE_TITLE, "This evaluation has no labelled features.")
            elif any(s.running for s in statuses):
                empty_card(SCORING_TITLE, "Progress is polled; this page refreshes itself.")
            elif not any(s.is_scored for s in statuses):
                empty_card(NOT_SCORED_TITLE, NOT_SCORED_BODY)
            else:
                await self._render_active_tab(evaluation_id)

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
        """The index the design does not draw (C7)."""
        with ui.element("div").style(
            "padding:18px 28px;display:flex;flex-direction:column;gap:12px;"
        ):
            empty_card(
                EMPTY_TITLE if not missing else f"No evaluation {missing}.",
                EMPTY_BODY,
            )
