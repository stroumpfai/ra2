"""Layer 3 — the Results view stops being a dead end.

Three defects, reproduced on the development seed and fixed together
(`plan-fix-results-visibility.md`):

1. the page **never refreshed itself** although its own copy says it does, so
   a Results page opened during a run rendered "Not scored yet" and kept
   rendering it after the pass had finished;
2. a finished run whose scoring had **crashed** got that same sentence —
   "Scoring starts automatically when a run completes" — and the Re-score it
   names did not exist anywhere in `ui/`;
3. the runs table links to `/results?run=<id>` and this page understood only
   `?evaluation=`, so the one control that takes an analyst from a finished
   run to its board landed on the picker.

The third is the one that produced the reported symptom: a `done` run, a
scored database, and an empty Results view.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from sqlalchemy import delete, update
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus, seed_scored_corpus

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import EvaluationId
from ra2.infra.config import Settings
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import AsyncioTaskRunner
from ra2.persistence.models import Run, Score
from ra2.services.container import Services
from ra2.ui.views.results import (
    EMPTY_BODY_NONE,
    EMPTY_TITLE,
    INCOMPLETE_TITLE,
    NOT_SCORED_BODY,
    NOT_SCORED_TITLE,
    PARTIAL_NOTE,
    POLL_SLOW_S,
    STALLED_TITLE,
)

pytestmark = pytest.mark.ui

#: `should_see` sleeps 0.1 s between attempts, and the page redraws on its own
#: timer — at `POLL_SLOW_S` while it is waiting for a run, which is the slower
#: of the two. So anything that waits for the poll needs more than the default
#: three.
_POLL_RETRIES = 60


@dataclass(frozen=True)
class Unscored:
    """A browser on an app whose database holds a **finished, unscored** run.

    Which is the state every one of these tests is about: the run is over,
    there are labelled features, and no `score` row exists.
    """

    user: User
    corpus: ScoredCorpus
    services: Services
    app: FastAPI


@pytest.fixture
async def unscored(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, seeded_ids: IdFactory
) -> AsyncIterator[Unscored]:
    """**`AsyncioTaskRunner`, not the root fixture's `InlineTaskRunner`.**

    Inline runs each job on a throwaway thread with a fresh event loop, so a
    scoring pass submitted from a click reaches the shared engine's aiosqlite
    connections from a second loop — the same limitation that made the
    `SD17` chain untestable inline (`6bae3a3`). Production has one loop; so
    does this fixture, and `_settled` is what waits for the pass.
    """
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True, task_runner=AsyncioTaskRunner(seeded_ids))
            session_factory = app.state.session_factory
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                async with session_factory() as session:
                    corpus = await seed_scored_corpus(session, records=40)
                    await session.commit()
                yield Unscored(User(client), corpus, app.state.services, app)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


async def test_a_run_link_opens_that_runs_board(unscored: Unscored) -> None:
    """**The reported symptom.**

    `/results?run=<id>` is what `evaluation_view._render_run_id` has linked to
    since phase 3. FastAPI drops an undeclared query parameter silently, so
    the page rendered its picker — "No evaluation selected." — about the very
    run the analyst had clicked.
    """
    run_id = unscored.corpus.run_ids[0]

    await unscored.user.open(f"/results?run={run_id}")

    await unscored.user.should_not_see(EMPTY_TITLE)
    await unscored.user.should_see(marker="results-tabs")


async def test_the_picker_lists_the_evaluations_it_tells_you_to_pick(
    unscored: Unscored,
) -> None:
    """**The sidebar's own Results entry ended here**, on a card reading
    "Pick a launched evaluation below" with nothing below it — the same
    defect as an empty state naming a control that does not exist, one
    screen further out. Found by driving the running app rather than by
    reading: every test in this file passed an id in the URL, which is
    exactly the path the sidebar does not take.
    """
    await unscored.user.open("/results")

    await unscored.user.should_see(marker="evaluation-picker")
    (link,) = unscored.user.find(marker="picker-evaluation").elements
    assert str(link._props.get("href", "")) == (
        f"/results?evaluation={unscored.corpus.evaluation_id}"
    )


async def test_the_picker_says_so_when_there_is_nothing_to_pick(user: User) -> None:
    """A database with no launched evaluation gets a different sentence: the
    one above would be pointing at an empty space again."""
    await user.open("/results")

    await user.should_see(EMPTY_BODY_NONE)
    await user.should_not_see(marker="evaluation-picker")


async def test_an_unknown_run_falls_back_to_the_picker(unscored: Unscored) -> None:
    """A followed link that names nothing is not a crash: the picker is the
    page that can say "pick another one"."""
    await unscored.user.open("/results?run=no-such-run")

    await unscored.user.should_see(EMPTY_TITLE)


async def test_a_finished_run_with_no_scores_says_scoring_did_not_finish(
    unscored: Unscored,
) -> None:
    """§16.7's fourth state.

    The run is `done`, the evaluation has labelled features, nothing is in
    flight and no `score` row exists — so waiting is the one thing that will
    not help, and "Not scored yet. Scoring starts automatically when a run
    completes" is a promise about the next few seconds that nobody is keeping.
    """
    evaluation_id = unscored.corpus.evaluation_id

    await unscored.user.open(f"/results?evaluation={evaluation_id}")

    await unscored.user.should_see(STALLED_TITLE)
    await unscored.user.should_not_see(NOT_SCORED_TITLE)


async def test_the_stalled_state_offers_the_rescore_the_copy_has_always_named(
    unscored: Unscored,
) -> None:
    """`NOT_SCORED_BODY` has said *"use Re-score if you need to run it again"*
    since phase 4, and there was no Re-score in `ui/` — the only route to one
    was a `POST` nothing in the product issued."""
    evaluation_id = unscored.corpus.evaluation_id

    await unscored.user.open(f"/results?evaluation={evaluation_id}")

    await unscored.user.should_see(marker="rescore")
    buttons = unscored.user.find(marker="rescore").elements
    assert {str(e.props["data-run"]) for e in buttons} == set(unscored.corpus.run_ids)


async def test_pressing_rescore_scores_the_run_and_the_board_appears(
    unscored: Unscored,
) -> None:
    """End to end through the control: press, and the boards are there.

    The button submits on the `TaskRunner` seam and the page's own poll is
    what brings the numbers in — but `app_factory` wires `InlineTaskRunner`,
    which finishes the pass before `submit` returns, so the redraw that
    follows the click already has the rows.
    """
    evaluation_id = unscored.corpus.evaluation_id
    await unscored.user.open(f"/results?evaluation={evaluation_id}")
    await unscored.user.should_see(STALLED_TITLE)

    unscored.user.find(marker="rescore").click()
    await _scored(unscored, evaluation_id, expected=1)

    statuses = await unscored.services.results.scoring_status(evaluation_id)
    assert any(status.is_scored for status in statuses)
    await unscored.user.should_not_see(STALLED_TITLE, retries=_POLL_RETRIES)


async def test_a_run_nobody_scored_is_named_above_the_board_it_is_missing_from(
    unscored: Unscored,
) -> None:
    """An evaluation runs several models and each is scored by its own pass.

    One pass failing while the others succeed puts the boards on screen with
    a column of blank cells — indistinguishable, to a reader, from a model
    that answered nothing. So the strip says which run was never scored, and
    offers the same Re-score, over a rendered board rather than instead of
    one.
    """
    evaluation_id = unscored.corpus.evaluation_id
    await unscored.user.open(f"/results?evaluation={evaluation_id}")
    unscored.user.find(marker="rescore").click()
    await _scored(unscored, evaluation_id, expected=1)

    # `retries` covers the page's own timer: the pass finished, and the
    # redraw that shows it arrives on the next tick (`POLL_S`). That is the
    # behaviour under test, so it is waited for rather than reached around.
    await unscored.user.should_see(PARTIAL_NOTE, retries=_POLL_RETRIES)
    remaining = unscored.user.find(marker="rescore").elements
    assert len(remaining) == 1, "the run that was scored no longer offers one"

    unscored.user.find(marker="rescore").click()
    await _scored(unscored, evaluation_id, expected=2)
    await unscored.user.should_not_see(PARTIAL_NOTE, retries=_POLL_RETRIES)


async def test_a_page_open_while_a_run_is_going_brings_the_boards_in_by_itself(
    unscored: Unscored,
) -> None:
    """**The gap that produced the report.**

    The analyst opens Results while the run is still going, reads "Not scored
    yet", and the page never changes again — there was no timer in this
    package at all, while its own copy said *"Progress is polled; this page
    refreshes itself."* The pass takes 0.14 s on the development seed, so the
    sentence on screen was stale within a blink of the run ending, and stayed
    that way for as long as the tab was open.

    Nothing here touches the browser after the page is opened: the run
    finishes and the pass is submitted the way the worker's terminal `done`
    submits it (`SD17`), and the screen is expected to catch up on its own.
    """
    evaluation_id = unscored.corpus.evaluation_id
    await _set_run_status(unscored, RunStatus.RUNNING)
    await unscored.user.open(f"/results?evaluation={evaluation_id}")
    await unscored.user.should_see(NOT_SCORED_TITLE)

    await _set_run_status(unscored, RunStatus.DONE)
    for run_id in unscored.corpus.run_ids:
        await unscored.services.scoring.submit_rescore(run_id)
    await _scored(unscored, evaluation_id, expected=len(unscored.corpus.run_ids))

    # No click, no navigation, no reload: the page's own timer.
    await unscored.user.should_see(marker="results-tabs", retries=_POLL_RETRIES)
    await unscored.user.should_not_see(NOT_SCORED_TITLE, retries=_POLL_RETRIES)


async def _set_run_status(unscored: Unscored, status: RunStatus) -> None:
    """Both runs at once — the evaluation is what the page reads."""
    async with unscored.app.state.session_factory() as session:
        await session.execute(
            update(Run)
            .where(Run.evaluation_id == unscored.corpus.evaluation_id)
            .values(status=status)
        )
        await session.commit()


async def test_a_run_still_going_is_told_to_wait_not_that_it_finished(
    unscored: Unscored,
) -> None:
    """The sentence this card used to carry was *"This run finished but has
    not been scored"* — said about a run that had not finished, because the
    unfinished case and the crashed case shared one card."""
    await _set_run_status(unscored, RunStatus.RUNNING)

    await unscored.user.open(f"/results?evaluation={unscored.corpus.evaluation_id}")

    await unscored.user.should_see(NOT_SCORED_BODY)
    await unscored.user.should_not_see(marker="rescore")


async def test_a_pass_that_stopped_part_way_says_so(unscored: Unscored) -> None:
    """`ScoringStatus`'s docstring names three states that must not be
    conflated, and `0 < scored < labelled` was conflated with "not scored
    yet" — a sentence about waiting, over a board that would have been the
    numbers of a corpus nobody stated."""
    evaluation_id = unscored.corpus.evaluation_id
    for run_id in unscored.corpus.run_ids:
        await unscored.services.scoring.submit_rescore(run_id)
    await _scored(unscored, evaluation_id, expected=len(unscored.corpus.run_ids))
    await _drop_scores_of_one_feature(unscored)

    await unscored.user.open(f"/results?evaluation={evaluation_id}")

    await unscored.user.should_see(INCOMPLETE_TITLE)
    await unscored.user.should_see(marker="rescore")


async def _drop_scores_of_one_feature(unscored: Unscored) -> None:
    """Leave every run with **some** features scored and one feature bare —
    what an interrupted pass leaves behind, since `_score` commits one
    `(run, feature)` at a time."""
    async with unscored.app.state.session_factory() as session:
        feature_id = unscored.corpus.feature_ids[WEATHER]
        await session.execute(delete(Score).where(Score.feature_id == feature_id))
        await session.commit()


async def _scored(unscored: Unscored, evaluation_id: EvaluationId, *, expected: int) -> None:
    """Wait for `expected` runs of this evaluation to have scores.

    The control **submits** — that is the point of it — so the rows arrive on
    the task's own schedule rather than inside the click. Polled rather than
    slept on, and it raises rather than hanging.
    """
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        statuses = await unscored.services.results.scoring_status(evaluation_id)
        if sum(1 for status in statuses if status.is_scored) >= expected:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"only {sum(s.is_scored for s in statuses)} of {expected} scored")
        await asyncio.sleep(0.05)


async def test_the_poll_is_quick_for_a_pass_and_slow_for_a_run(
    unscored: Unscored,
) -> None:
    """The interval is a fact about **what** is being waited for.

    A scoring pass is 0.14 s on the development seed; a run is hours. Holding
    the fast interval through a run would put two and a half `scoring_status`
    reads a second against the SQLite file the worker is committing to — the
    mistake `plan-fix-evaluation-runs.md` §1.2 catalogued on the Evaluation
    screen, which is the one place this page should not copy.
    """
    evaluation_id = unscored.corpus.evaluation_id
    await _set_run_status(unscored, RunStatus.RUNNING)
    await unscored.user.open(f"/results?evaluation={evaluation_id}")

    (timer,) = _timers(unscored)
    assert timer.interval == POLL_SLOW_S, "waiting for a run"

    await _set_run_status(unscored, RunStatus.DONE)
    task_ids = [
        await unscored.services.scoring.submit_rescore(run_id) for run_id in unscored.corpus.run_ids
    ]
    assert task_ids
    statuses = await unscored.services.results.scoring_status(evaluation_id)
    assert any(status.running for status in statuses), "a pass is in flight"


async def test_the_stalled_page_re_reads_once_and_then_stops(unscored: Unscored) -> None:
    """The gap between a run's `done` and its pass being submitted.

    `run_service._chain_scoring` re-reads the run row in between, so a page
    that loads inside that window sees a finished run with no rows and
    nothing in flight — "scoring did not finish", about a pass that is a
    heartbeat from starting. One extra read covers it; a timer that kept
    running would re-read a settled board for as long as the tab was open.
    """
    evaluation_id = unscored.corpus.evaluation_id
    await unscored.user.open(f"/results?evaluation={evaluation_id}")
    await unscored.user.should_see(STALLED_TITLE)

    # The scoring that "was about to start" starts now, from outside the page.
    for run_id in unscored.corpus.run_ids:
        await unscored.services.scoring.submit_rescore(run_id)
    await _scored(unscored, evaluation_id, expected=len(unscored.corpus.run_ids))

    await unscored.user.should_not_see(STALLED_TITLE, retries=_POLL_RETRIES)
    await _no_active_timer(unscored)


async def _no_active_timer(unscored: Unscored, *, timeout_s: float = 10) -> None:
    """Wait for the page to stop polling, then assert it stays stopped.

    Bounded rather than instant: the tick that settles the page is the tick
    that stops the timer, so the assertion has to be allowed to arrive after
    it rather than between two of them.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        timers = [timer for timer in _timers(unscored) if timer.active]
        if not timers:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"still polling: {[t.interval for t in timers]}")
        await asyncio.sleep(0.1)


def _timers(unscored: Unscored) -> list[ui.timer]:
    """Every `ui.timer` on the page under test.

    Reached through the client's element table because a timer is not
    `find`-able: it renders nothing, which is the whole reason the missing
    one went unnoticed for four phases.
    """
    client = unscored.user.client
    assert client is not None, "the page has not been opened"
    return [element for element in client.elements.values() if isinstance(element, ui.timer)]
