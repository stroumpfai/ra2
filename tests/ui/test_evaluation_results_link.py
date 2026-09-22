"""Layer 3 — the Evaluation screen says when a run has a board, and where.

Two small things, both from the reported session
(`plan-fix-results-visibility.md` §3 e). The analyst watched the progress
column until the run said `done`, and then:

- the column header still read **"In progress"** — a constant string, the
  design's own wording for the state the design drew, rendered in every other
  state too;
- nothing on that screen said the boards existed. The only route to them was
  a link in the runs table two cards further down, and it led to the picker
  (`test_results_visibility.py`).

So the header now reads "Runs" once nothing is moving, and a card whose run
**has** scores carries the link. Only then: a link to "Not scored yet" is the
dead end this whole fix is about.
"""

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from itertools import count

import httpx
import pytest
from fastapi import FastAPI
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.evaluation_view import (
    PROGRESS_TITLE,
    PROGRESS_TITLE_SETTLED,
    RESULTS_LINK_LABEL,
)

pytestmark = pytest.mark.ui


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"ui-mismatch-{next(self._counter):04d}"


@dataclass(frozen=True)
class Finished:
    user: User
    corpus: ScoredCorpus


@pytest.fixture
async def finished(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Finished]:
    """A launched evaluation whose runs are `done` **and scored**.

    Scored by the real pass rather than by hand-written rows, because what
    the card reads is `ScoringStatusView.is_scored` — the same property the
    Results view branches on, so the link and the page it opens cannot
    disagree about whether there is anything there.
    """
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
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
                scoring = ScoringService(
                    session_factory=session_factory,
                    ground_truth=GroundTruthRepository(),
                    task_runner=None,  # type: ignore[arg-type]
                    clock=frozen_clock,
                    id_factory=_Ids(),
                )
                for run_id in corpus.run_ids:
                    await scoring.score_run(run_id)
                yield Finished(User(client), corpus)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


async def test_a_scored_run_carries_the_link_to_its_board(finished: Finished) -> None:
    await finished.user.open("/evaluation")

    await finished.user.should_see(marker="progress-results-link")
    links = finished.user.find(marker="progress-results-link").elements
    targets = {str(link._props.get("href", "")) for link in links}
    assert targets == {f"/results?run={run_id}" for run_id in finished.corpus.run_ids}
    assert all(RESULTS_LINK_LABEL in str(link._text) for link in links)


async def test_the_header_stops_saying_in_progress_once_nothing_is(
    finished: Finished,
) -> None:
    """The design's wording is kept for the state the design drew — a run in
    flight — and dropped for the state it does not: every card `done`, under
    a header that says the opposite."""
    await finished.user.open("/evaluation")

    (title,) = finished.user.find(marker="progress-title").elements
    assert str(title._text) == PROGRESS_TITLE_SETTLED
    assert str(title._props["data-settled"]) == "true"
    # The design's wording is still what an in-flight run gets; this asserts
    # the two are different words rather than one constant doing both jobs.
    assert str(title._text) != PROGRESS_TITLE
