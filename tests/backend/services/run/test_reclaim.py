"""Restart detection: once, at process start, and nowhere else.

A process that dies mid-run leaves its `run` row saying `running`, because
nothing updates it on the way down. `reclaim_orphans` relabels those
`interrupted` — never resumes them (§15 F8) — and it is called from exactly one
place, the composition root's startup.

**That precondition is the design, not an implementation note.** At startup this
process is executing nothing, so a `running` row is stale *unconditionally*:
there is no set to consult, no claim to hold and no window to get wrong.

What it replaced reclaimed on every read path, guarded by an in-memory record of
which runs this process was executing. That guard had two gaps a few
microseconds wide — between `_start` committing `running` and the worker
claiming the run, and between the worker letting go and `cancel` recording the
stop — and the Evaluation view's poll reaches those read paths twice a tick for
the length of a run. Each gap wrote `_ERROR_INTERRUPTED_BY_RESTART` about a
process that was fine, and the cancel one additionally made **Stop** report
itself as a crash, because `_finish_cancelled` re-reads the status and then
correctly declines to overwrite an outcome it did not produce.

So the assertion that matters most here is the negative one:
`test_no_read_path_reclaims`. It is what makes the two gaps unreachable rather
than merely closed, and it fails on the previous implementation — which is the
only reason to trust that this file is testing the change and not the weather.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.run.conftest import answer
from tests.backend.services.run.test_in_flight import _wait_for_terminal
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import RunId
from ra2.persistence.repositories.run_repo import RunRepository
from ra2.services.run_service import _ERROR_CANCELLED, _ERROR_INTERRUPTED_BY_RESTART

pytestmark = pytest.mark.backend


async def _force_status(
    db_session_factory: async_sessionmaker[AsyncSession], run_id: RunId, status: RunStatus
) -> None:
    """A row in a state this process did not put it in — which is exactly what
    a previous process leaves behind."""
    async with db_session_factory() as session:
        await RunRepository(session).set_status(run_id, status)
        await session.commit()


async def test_a_run_left_running_is_relabelled_interrupted(
    seed, make_run_service, db_session_factory, run_row
):
    """The whole job, on the row a dead process leaves."""
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))
    await _force_status(db_session_factory, seeded.run_id, RunStatus.RUNNING)

    assert await service.reclaim_orphans() == 1

    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.INTERRUPTED
    assert run.error == _ERROR_INTERRUPTED_BY_RESTART
    # `interrupted` is the one state a human moves out of, so nothing finished
    # and Resume is the way on (§15 F8).
    assert run.finished_at is None
    assert (await service.get(seeded.run_id)).is_resumable is True


@pytest.mark.parametrize(
    "status",
    [RunStatus.QUEUED, RunStatus.DONE, RunStatus.FAILED, RunStatus.INTERRUPTED],
)
async def test_reclaim_touches_nothing_but_running(
    seed, make_run_service, db_session_factory, run_row, status
):
    """`running` is the only status a dead process can leave behind, and the
    only one that is a lie once it has. A `queued` run is honestly queued — the
    worker never reached it — and rewriting a `done` run would be the app
    inventing an outcome."""
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))
    await _force_status(db_session_factory, seeded.run_id, status)

    assert await service.reclaim_orphans() == 0
    assert RunStatus((await run_row(seeded.run_id)).status) is status


async def test_no_read_path_reclaims(seed, make_run_service, db_session_factory, run_row):
    """**The inversion.** Reads report; they do not decide.

    Every read on the Evaluation screen goes through one of these three, and
    the previous implementation relabelled from all of them. This test fails
    there — the first call alone flips the row — which is what makes it a test
    of the change rather than of nothing.

    The row below is stale, and stays stale until somebody asks the question at
    the one moment the answer cannot be wrong. That is the point: a stale row
    read honestly is recoverable, and a live row declared dead is not.
    """
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))
    await _force_status(db_session_factory, seeded.run_id, RunStatus.RUNNING)

    assert (await service.progress(seeded.run_id)).status is RunStatus.RUNNING
    assert (await service.get(seeded.run_id)).status is RunStatus.RUNNING
    listed = (await service.list_runs(seeded.evaluation_id)).items
    assert [view.status for view in listed if view.run_id == seeded.run_id] == [RunStatus.RUNNING]

    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.RUNNING
    assert run.error is None


async def test_a_run_in_flight_is_untouched_by_the_reads_around_it(
    seed, make_run_service, async_task_runner, run_row
):
    """The defect that started this, from the other side.

    A worker mid-record, polled exactly as the view polls it. Before, a read
    landing in either claim gap wrote the process-death sentence about this
    run and the worker carried on extracting into a row marked `interrupted` —
    while the table offered a **Resume** that would have put a second worker on
    it. There is now no read that can write, so the interleaving does not need
    constructing.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    for _ in range(20):
        assert (await service.progress(seeded.run_id)).status is RunStatus.RUNNING
        await asyncio.sleep(0)

    assert (await run_row(seeded.run_id)).error is None

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_a_stop_is_recorded_as_a_stop_and_not_as_a_crash(
    seed, make_run_service, async_task_runner, run_row
):
    """`Task.cancel()` only schedules, so the worker unwinds while `cancel` is
    still awaiting and the row says `running` throughout. That used to be a
    window a read could reclaim — after which `_finish_cancelled` found
    `interrupted`, correctly declined to overwrite it, and left the analyst's
    Stop recorded as a process death. Polled hard across the stop."""
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    stop = asyncio.create_task(service.cancel(seeded.run_id))
    while not stop.done():
        await service.progress(seeded.run_id)
        await asyncio.sleep(0)
    await stop

    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.INTERRUPTED
    assert run.error == _ERROR_CANCELLED

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)


async def test_reclaiming_a_run_it_then_resumes_finds_exactly_the_hole(
    seed, make_run_service, reporter, extractions_of, db_session_factory
):
    """Reclaim is a relabel, not a loss. The run picks up where it stopped.

    This is the pair to §15 F8: reclaim makes the row `interrupted`, and
    `interrupted` is the state Resume acts on. A reclaim that cost the
    committed rows, or that left the resume query unable to find the hole,
    would be a worse answer than leaving the row wrong.
    """
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))

    # One record committed, then the process "dies": the row is forced back to
    # `running` with two records still pending.
    await service.execute_run(seeded.run_id, reporter)
    assert len(await extractions_of(seeded.run_id)) == 3
    async with db_session_factory() as session:
        await session.delete((await extractions_of(seeded.run_id))[2])
        await session.commit()
    await _force_status(db_session_factory, seeded.run_id, RunStatus.RUNNING)

    assert await service.reclaim_orphans() == 1
    assert (await service.get(seeded.run_id)).is_resumable is True

    await service.resume(seeded.run_id)

    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.DONE
    assert view.error is None
    assert len(await extractions_of(seeded.run_id)) == 3
