"""A finished run scores itself — `SD17`, as a test at the seam.

    Scoring is **chained, not triggered**. The run worker's terminal `done`
    submits the scoring job; there is no Score button, and the design draws
    none. (sw-design.md §16.1)

That sentence was true of the design and false of the code for four phases.
`RunService` took no scorer, `ScoringService.submit` had no caller anywhere in
`ra2/`, and a finished run therefore sat at **"Not scored yet"** forever while
the Results view told the analyst *"Scoring starts automatically when a run
completes"*. There is no Re-score control either, so the only way to a Results
board was a `POST /api/v1/runs/{id}/rescore` that nothing in the product
issues.

**Why every existing test was green.** Each layer was exercised alone and each
built the chain by hand: every scoring, results, ranking and mismatch conftest
calls `score_run` itself, and `tests/e2e/conftest.py` seeds `score` rows
directly — its own comment says *"nothing in the product writes those except
the run worker and the scoring pass"*. A seam nobody crosses in a test is a
seam nobody notices is missing.

So the load-bearing test here is `test_a_finished_run_is_scored_through_the_
composition_root`: it goes through `create_app`, which is the thing that was
wrong. The rest pin the conditions — only `done`, never a partial corpus.
"""

import asyncio
from collections.abc import Callable

import pytest
from tests.backend.services.run.conftest import answer
from tests.backend.services.run.test_in_flight import _wait_for_terminal
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import RunId, TaskId
from ra2.infra.tasks import AsyncioTaskRunner
from ra2.services.container import Services

pytestmark = pytest.mark.backend


class RecordingScorer:
    """A `ScoreSubmitter` that records rather than scores.

    Structural, like every other double here: `ScoringService` satisfies the
    protocol without either module importing the other, and so does this.
    """

    def __init__(self) -> None:
        self.submitted: list[RunId] = []

    def submit(self, run_id: RunId) -> TaskId:
        self.submitted.append(run_id)
        return TaskId(f"score:{run_id}")


async def test_a_completed_run_submits_its_own_scoring(seed, make_run_service, reporter):
    """The chain itself, at the service."""
    scorer = RecordingScorer()
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()), scorer=scorer)

    await service.execute_run(seeded.run_id, reporter)

    assert (await service.get(seeded.run_id)).status is RunStatus.DONE
    assert scorer.submitted == [seeded.run_id]


async def test_an_interrupted_run_is_never_scored(seed, make_run_service, reporter):
    """§16.1: a partial corpus produces real-looking numbers over an unstated
    denominator, which is precisely what §11.4's suppression rule exists to
    prevent at the other end of the scale.

    `scoring_service` refuses it too — `rescore` on an interrupted run is a
    409. This asserts the worker does not even ask, so the refusal is a second
    line of defence rather than the only one.
    """
    scorer = RecordingScorer()
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer(), fail_from=1), scorer=scorer)

    await service.execute_run(seeded.run_id, reporter)

    assert (await service.get(seeded.run_id)).status is RunStatus.INTERRUPTED
    assert scorer.submitted == []


async def test_a_stopped_run_is_never_scored(seed, make_run_service, async_task_runner, run_row):
    """The same rule from the other direction: a run somebody stopped has the
    same hole in its corpus as one the endpoint abandoned."""
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate, gate_from=1)
    scorer = RecordingScorer()
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner, scorer=scorer)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(2)
    await service.cancel(seeded.run_id)

    assert RunStatus((await run_row(seeded.run_id)).status) is RunStatus.INTERRUPTED
    assert scorer.submitted == []

    # Released **and waited for**: a job still unwinding when the next test
    # disposes this engine surfaces as an unraisable aiosqlite thread error in
    # whatever runs next, which is a hard failure to attribute to its cause.
    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)


async def test_a_finished_run_is_scored_through_the_composition_root(
    seed,
    build_app,
    async_task_runner,
    extractions_of,
):
    """**The one that was missing.**

    Through `create_app`, because the defect was in the wiring and nowhere
    else: every part worked, and nothing joined them. A service-level test with
    a scorer passed in by hand would have been green the whole time this was
    broken.

    Asserted on `score` rows rather than on a recorder, for the same reason:
    what needs proving is that the real `ScoringService` ran, not that a
    `submit` was called.

    **Not** asserted on `is_scored`. This fixture's corpus carries no
    `unfall_row` ground truth, so `_scoreable_count` is 0 and the run is
    correctly "nothing scoreable" — a fact about the seeded corpus, not about
    the chain. Whether scoring produces the right *numbers* is the scoring
    suite's question; this file asks only whether anything asks it.
    """
    seeded = await seed(records=3)
    app = await build_app(
        llm_client=FakeLLMClient(response=answer()), seed=1, task_runner=async_task_runner
    )
    services: Services = app.state.services

    task_id = await services.run.launch_runs(seeded.evaluation_id)
    await _wait_for_terminal(async_task_runner, task_id)
    # The scoring job is a **second** task, submitted by the first. Waiting for
    # the run's own task says nothing about it, so wait for the chain to settle
    # rather than for the thing that starts it.
    await _wait_until(lambda: _scored(async_task_runner))

    assert len(await extractions_of(seeded.run_id)) == 3
    assert (await services.run.get(seeded.run_id)).status is RunStatus.DONE

    (status,) = await services.results.scoring_status(seeded.evaluation_id)
    assert status.scored_features > 0, (
        "a finished run must be scored without anybody pressing anything (SD17); "
        "before the chain existed this was 0 forever"
    )


def _scored(runner: AsyncioTaskRunner) -> bool:
    """Has a `score:` job been submitted *and* finished?

    Read off the runner's own progress table rather than off the database, so
    the wait is about the chain rather than about what the chain produced —
    the assertions below are what judge the result.
    """
    tasks = [t for t in runner._table._tasks.values() if t.name.startswith("score:")]
    return bool(tasks) and all(t.is_terminal for t in tasks)


async def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 10.0) -> None:
    """Raise rather than hang, for `_wait_for_terminal`'s reason."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout_s}s")
        await asyncio.sleep(0.02)
