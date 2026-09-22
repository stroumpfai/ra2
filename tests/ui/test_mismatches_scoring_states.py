"""Layer 3 — Mismatches stops telling a crashed pass as a perfect score.

    Run 1 scored, run 2's pass crashed. The analyst picks run 2 in the run
    chip. `any(is_scored)` is `True`, so the view renders the table. Run 2 has
    no `mismatch` rows, and the run is not a filter — so the card reads "No
    mismatches in this run. Every labelled feature this model answered, it
    answered correctly."
    (`plan-scoring-visibility-follow-ups.md` §1.2)

Not an ambiguous sentence: a **false and flattering** one, on the one screen
in the product where a human is deciding which model to believe. The Results
boards for the same run draw blank cells and now name them; this screen said
the run was perfect.

The fix is per-run rather than per-evaluation, and the sentences come from
`views/scoring_states.py` so the two screens cannot drift into two accounts
of one fact.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from itertools import count

import httpx
import pytest
from fastapi import FastAPI
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from sqlalchemy import delete, update
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import RunId
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import AsyncioTaskRunner
from ra2.persistence.models import Run, Score
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.container import Services
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.mismatches_view import NO_MISMATCHES_BODY, NO_MISMATCHES_TITLE
from ra2.ui.views.scoring_states import (
    INCOMPLETE_TITLE,
    NOT_SCORED_TITLE,
    STALLED_TITLE,
)

pytestmark = pytest.mark.ui

#: `should_see` sleeps 0.1 s between attempts and this screen now redraws on
#: its own timer, at `POLL_SLOW_S` while it waits for a run.
_POLL_RETRIES = 60


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"ui-mismatch-{next(self._counter):04d}"


@dataclass(frozen=True)
class Half:
    """An evaluation with **two** runs, of which exactly one was scored.

    The shape the defect needs and no fixture had: every existing Mismatches
    fixture scores all runs or none, and `any(is_scored)` cannot be wrong
    about a set where every member agrees.
    """

    user: User
    corpus: ScoredCorpus
    services: Services
    app: FastAPI

    @property
    def scored_run(self) -> RunId:
        return self.corpus.run_ids[0]

    @property
    def unscored_run(self) -> RunId:
        return self.corpus.run_ids[1]


@pytest.fixture
async def half_scored(
    app_factory: Callable[..., FastAPI],
    migrated_db: Settings,
    frozen_clock: Clock,
    seeded_ids: IdFactory,
) -> AsyncIterator[Half]:
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
                scoring = ScoringService(
                    session_factory=session_factory,
                    ground_truth=GroundTruthRepository(),
                    task_runner=None,  # type: ignore[arg-type]
                    clock=frozen_clock,
                    id_factory=_Ids(),
                )
                # **Only the first run.** The second is what a pass that died
                # leaves behind: a finished run, and not one `score` row.
                await scoring.score_run(corpus.run_ids[0])
                yield Half(User(client), corpus, app.state.services, app)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


def _url(half: Half, run_id: RunId) -> str:
    return f"/mismatches?evaluation={half.corpus.evaluation_id}&run={run_id}"


async def test_the_run_whose_pass_died_is_not_called_correct(half_scored: Half) -> None:
    """**The reported failure.** Nothing about run 2 is known, and the screen
    said everything about it was right."""
    await half_scored.user.open(_url(half_scored, half_scored.unscored_run))

    await half_scored.user.should_not_see(NO_MISMATCHES_TITLE)
    await half_scored.user.should_not_see(NO_MISMATCHES_BODY)
    await half_scored.user.should_see(STALLED_TITLE)


async def test_the_run_that_was_scored_still_shows_its_list(half_scored: Half) -> None:
    """The other half of per-run: the sibling run is scored and unaffected.

    A fix that suppressed the list whenever *any* run of the evaluation was
    unscored would trade one wrong screen for another.
    """
    await half_scored.user.open(_url(half_scored, half_scored.scored_run))

    await half_scored.user.should_see(marker="table-mismatches")
    await half_scored.user.should_not_see(STALLED_TITLE)


async def test_the_run_chip_survives_an_unscored_run(half_scored: Half) -> None:
    """The toolbar renders **whatever** the scoring state is.

    It carries the run chip, so a screen that dropped it because this run has
    no scores would strand the analyst on the one run with nothing to show
    and no way to reach the one that has.
    """
    await half_scored.user.open(_url(half_scored, half_scored.unscored_run))

    # The run chip specifically: it is the control that reaches the other run.
    await half_scored.user.should_see(marker="chip-run")
    await half_scored.user.should_see(STALLED_TITLE)


async def test_the_stalled_run_offers_a_rescore_naming_the_run_the_chip_names(
    half_scored: Half,
) -> None:
    """One button, labelled with the ordinal the chip above it uses — "run 2"
    in both places or the analyst is reading about two different runs."""
    await half_scored.user.open(_url(half_scored, half_scored.unscored_run))

    (button,) = half_scored.user.find(marker="rescore").elements
    assert str(button.props["data-run"]) == str(half_scored.unscored_run)
    await half_scored.user.should_see("Re-score run 2")


async def test_pressing_rescore_brings_the_run_back(half_scored: Half) -> None:
    """End to end through the control the card names."""
    await half_scored.user.open(_url(half_scored, half_scored.unscored_run))
    await half_scored.user.should_see(STALLED_TITLE)

    half_scored.user.find(marker="rescore").click()

    # The control **submits**; the rows arrive on the task's own schedule,
    # which is why the card names a page that refreshes itself.
    await _both_scored(half_scored)
    await half_scored.user.should_not_see(STALLED_TITLE, retries=_POLL_RETRIES)


async def test_a_part_way_pass_says_so_rather_than_showing_a_short_list(
    half_scored: Half,
) -> None:
    """`0 < scored < labelled` — the state `ScoringStatus`'s own docstring
    says must not be conflated.

    A list drawn from half a pass is a list an analyst reviews as if it were
    the whole one, and the rows that are missing are invisible by definition.
    """
    async with half_scored.app.state.session_factory() as session:
        feature_id = half_scored.corpus.feature_ids["Witter0Ausw"]
        await session.execute(
            delete(Score).where(
                Score.run_id == half_scored.scored_run, Score.feature_id == feature_id
            )
        )
        await session.commit()

    await half_scored.user.open(_url(half_scored, half_scored.scored_run))

    await half_scored.user.should_see(INCOMPLETE_TITLE)
    await half_scored.user.should_not_see(marker="table-mismatches")


async def test_a_run_still_going_is_told_to_wait(half_scored: Half) -> None:
    """The third sentence of the split: a run that has not finished is
    waiting, not broken, and gets no button — `submit_rescore` would refuse
    it with a 409."""
    async with half_scored.app.state.session_factory() as session:
        await session.execute(
            update(Run).where(Run.id == half_scored.unscored_run).values(status=RunStatus.RUNNING)
        )
        await session.commit()

    await half_scored.user.open(_url(half_scored, half_scored.unscored_run))

    await half_scored.user.should_see(NOT_SCORED_TITLE)
    await half_scored.user.should_not_see(marker="rescore")


async def _both_scored(half: Half, *, timeout_s: float = 10) -> None:
    """Wait for every run of the evaluation to have scores. Raises rather
    than hanging, so a chain that never ran fails as a message."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        statuses = await half.services.results.scoring_status(half.corpus.evaluation_id)
        if all(status.is_scored for status in statuses):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"only {sum(s.is_scored for s in statuses)} run(s) scored")
        await asyncio.sleep(0.05)


def test_both_screens_say_it_with_the_same_words() -> None:
    """One module, two screens (`plan-scoring-visibility-follow-ups.md` 1e).

    Asserted by **identity**, not by equality of two strings: two modules
    holding the same sentence today are two sentences one edit apart, which
    is exactly how "Not scored yet." came to exist twice with two different
    bodies and two different meanings.
    """
    from ra2.ui.views import mismatches_view as mismatches
    from ra2.ui.views import results, scoring_states

    assert results.NOT_SCORED_TITLE is scoring_states.NOT_SCORED_TITLE
    assert results.NOT_SCORED_BODY is scoring_states.NOT_SCORED_BODY
    assert results.STALLED_TITLE is scoring_states.STALLED_TITLE
    assert results.INCOMPLETE_TITLE is scoring_states.INCOMPLETE_TITLE
    assert mismatches.NOT_SCORED_TITLE is scoring_states.NOT_SCORED_TITLE
    assert mismatches.NOT_SCORED_BODY is scoring_states.NOT_SCORED_BODY
