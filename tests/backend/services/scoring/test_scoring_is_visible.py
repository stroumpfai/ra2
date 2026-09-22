"""A scoring pass can be seen while it runs and after it fails.

    `ScoringStatus.running` is the literal `False`. Nothing joins the task
    runner to the status, so §16.7's **"Scoring…"** state is unreachable by
    construction. (plan-fix-results-visibility.md §3 b)

That was true for four phases, and it is why a finished run whose scoring had
crashed and one whose scoring was still going rendered the same sentence —
"Not scored yet" — forever. The run worker logged the task id and dropped it;
`AsyncioTaskRunner` recorded the crash in an in-memory table and logged
nothing; `ScoringService` logged nothing at all.

The three properties here are what make the Results view able to tell those
apart: `running` is true while a pass is in flight, it is true from the moment
`submit` returns rather than from whenever the loop gets to the coroutine, and
a pass that raises still clears it.
"""

import asyncio
from collections.abc import Callable
from itertools import count

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.scoring.conftest import SeededIds
from tests.fixtures.scored_corpus import ScoredCorpus

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import RunId
from ra2.infra.tasks import AsyncioTaskRunner, TaskStatus
from ra2.persistence.models import Run
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.errors import NotFoundError, RunNotScoreableError
from ra2.services.scoring_service import ScoringService

pytestmark = pytest.mark.backend


class _TaskIds:
    """Task ids a test can read back. `IdFactory`, structurally."""

    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"task-{next(self._counter):04d}"


@pytest.fixture
def runner() -> AsyncioTaskRunner:
    return AsyncioTaskRunner(_TaskIds())


@pytest.fixture
def service_with(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: object,
    runner: AsyncioTaskRunner,
) -> Callable[..., ScoringService]:
    def build(*, ground_truth: object | None = None) -> ScoringService:
        return ScoringService(
            session_factory=db_session_factory,
            ground_truth=ground_truth or GroundTruthRepository(),  # type: ignore[arg-type]
            task_runner=runner,
            clock=frozen_clock,  # type: ignore[arg-type]
            id_factory=SeededIds(),
        )

    return build


async def _status_running(
    service: ScoringService,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: RunId,
) -> bool:
    async with session_factory() as session:
        return (await service.status(session, run_id)).running


async def _wait_terminal(runner: AsyncioTaskRunner, task_id: str, *, timeout_s: float = 10) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not runner.progress(task_id).is_terminal:  # type: ignore[arg-type]
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("the task never reached a terminal status")
        await asyncio.sleep(0.01)


async def test_a_submitted_pass_is_running_before_the_loop_reaches_it(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    db_session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncioTaskRunner,
) -> None:
    """**The gap that made the flag useless.**

    `submit` returns a task id and returns immediately; the coroutine it
    scheduled has not started. A Results page polling in that window asked
    "is scoring running?" and — had the flag been set inside the coroutine —
    would have been told no about a pass already queued, which is the same
    wrong answer as the hardcoded `False`.
    """
    service = service_with()
    run_id = seeded.run_ids[0]

    task_id = service.submit(run_id)

    # Not a single `await` in between: this is the state of the world in the
    # same tick as the submit.
    assert await _status_running(service, db_session_factory, run_id) is True
    await _wait_terminal(runner, task_id)
    assert runner.progress(task_id).status is TaskStatus.OK
    assert await _status_running(service, db_session_factory, run_id) is False


async def test_a_failing_pass_stops_being_running(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    db_session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncioTaskRunner,
) -> None:
    """A crash must not leave the run marked as scoring for the life of the
    process: "scoring…" is the one state with no control on it, so a stuck
    flag is a screen an analyst cannot act on."""
    service = service_with(ground_truth=_ExplodingGroundTruth())
    run_id = seeded.run_ids[0]

    task_id = service.submit(run_id)
    await _wait_terminal(runner, task_id)

    assert runner.progress(task_id).status is TaskStatus.FAILED
    assert await _status_running(service, db_session_factory, run_id) is False


async def test_a_failing_pass_is_logged_without_any_delivery_content(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    runner: AsyncioTaskRunner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The line that was missing, and the rule it has to keep.

    A scoring failure produced **no** log output at all, so the only record
    of it was the in-memory task table — gone at the next restart. The line
    added for it carries ids, counts and the exception **type**; never
    `str(exc)`, because a SQLAlchemy error interpolates bound parameters into
    its message and a bound parameter here is a narrative (Do-NOT #13).
    """
    service = service_with(ground_truth=_ExplodingGroundTruth())
    run_id = seeded.run_ids[0]

    with caplog.at_level("INFO"):
        task_id = service.submit(run_id)
        await _wait_terminal(runner, task_id)

    messages = [record.getMessage() for record in caplog.records]
    assert any("scoring failed after" in message for message in messages), messages
    assert any(f"task {task_id}" in message and "failed" in message for message in messages)
    # The secret the exception was carrying never reaches a log line.
    assert not any(_SECRET in message for message in messages)


async def test_submit_rescore_refuses_before_it_schedules_anything(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    runner: AsyncioTaskRunner,
) -> None:
    """The refusals have to reach the caller as a 404 and a 409, and an
    exception raised inside a scheduled task reaches nobody but the task
    table — so they are raised **before** anything is submitted. Asserted on
    the runner: a refused re-score leaves no task behind to poll."""
    service = service_with()

    with pytest.raises(NotFoundError):
        await service.submit_rescore(RunId("no-such-run"))

    assert runner._table._tasks == {}


async def test_submit_rescore_refuses_a_run_that_is_not_done(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    db_session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncioTaskRunner,
) -> None:
    """§16.1: a partial corpus produces real-looking numbers over an unstated
    denominator. The scheduled path refuses it exactly as the awaited one
    does."""
    service = service_with()
    run_id = seeded.run_ids[0]
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.INTERRUPTED
        await session.commit()

    with pytest.raises(RunNotScoreableError):
        await service.submit_rescore(run_id)

    assert await _status_running(service, db_session_factory, run_id) is False
    assert runner._table._tasks == {}


async def test_a_submitted_rescore_runs_the_pass_again(
    seeded: ScoredCorpus,
    service_with: Callable[..., ScoringService],
    db_session_factory: async_sessionmaker[AsyncSession],
    runner: AsyncioTaskRunner,
) -> None:
    """What the API's `202 Accepted` now describes: work that was scheduled,
    under a task id the caller can poll."""
    service = service_with()
    run_id = seeded.run_ids[0]
    await service.score_run(run_id)

    task_id = await service.submit_rescore(run_id)
    await _wait_terminal(runner, task_id)

    progress = runner.progress(task_id)
    assert progress.status is TaskStatus.OK
    assert progress.name == f"rescore:{run_id}"
    async with db_session_factory() as session:
        status = await service.status(session, run_id)
    assert status.scored_features > 0


#: The value `_ExplodingGroundTruth` hides in its exception message — a stand-in
#: for the narrative a SQLAlchemy error would interpolate from bound parameters.
_SECRET = "Fahrzeug prallte gegen die Leitplanke"


class _ExplodingGroundTruth:
    """A `GroundTruthProvider` whose read raises, with something in the message
    that must never be logged."""

    async def values_for(self, *args: object, **kwargs: object) -> dict[str, str]:
        raise RuntimeError(f"(pysqlite) near: {_SECRET}")

    async def projections_for(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError(f"(pysqlite) near: {_SECRET}")
