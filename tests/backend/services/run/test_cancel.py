"""Stopping a run somebody has decided not to wait for.

The verb exists because of what a run costs. A model answering one record in
minutes spends essentially all of its time inside one `LLMClient.extract`, so
until now the only ways out of a launch against a misconfigured endpoint were
to wait for `_MAX_CONSECUTIVE_ENDPOINT_ERRORS` × `RA2_LLM_TIMEOUT_S` or to
kill the process (`plan-fix-evaluation-runs.md` §1.1 e).

Three properties, and each has a way of looking right while being wrong:

- **It stops this run, not the job.** A job covers every run of an evaluation
  and executes them serially, so cancelling at job level would make "stop this
  run" mean "abandon the evaluation" — and the runs after it are exactly the
  ones still being waited on.
- **The status is written.** A cancelled task can have `CancelledError`
  re-raised at any later await inside it, so a handler that records the stop
  from *within* the worker is the natural implementation and the one that
  silently leaves the row `running`.
- **Committed work survives.** Stopping is not discarding. Resume picks the
  run up from the hole.

These need `AsyncioTaskRunner` and `FakeLLMClient(gate=…)` — `InlineTaskRunner`
drives work to completion before `submit()` returns, so there is never
anything in flight to stop (Stage 0).
"""

import asyncio

import pytest
from tests.backend.services.run.conftest import DEFAULT_MODEL, answer
from tests.backend.services.run.test_in_flight import _wait_for_terminal
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.services.errors import NotFoundError, RunNotActiveError

pytestmark = pytest.mark.backend

SECOND_MODEL = "qwen2.5:14b-instruct-q6_K"


async def test_stopping_a_running_run_interrupts_it_and_keeps_what_committed(
    seed, make_run_service, async_task_runner, extractions_of
):
    """The whole verb, in one run: two records answered, the third held open,
    and a stop while it is in flight."""
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate, gate_from=2)
    seeded = await seed(records=5)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(3)

    await service.cancel(seeded.run_id)
    await _wait_for_terminal(async_task_runner, task_id)

    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.is_resumable is True
    # Stopping is not discarding: the two that committed are still there.
    assert len(await extractions_of(seeded.run_id)) == 2
    assert view.records_done == 2

    # Released so the gated call is not left holding the loop at teardown.
    gate.set()


async def test_a_stopped_run_is_not_reported_as_failed(seed, make_run_service, async_task_runner):
    """`execute_run` catches `Exception`, and `CancelledError` is a
    `BaseException` — which is the whole reason a stopped run is not filed as
    a failure. A run somebody stopped did not fail, and `failed` is terminal
    while `interrupted` is the one state Resume acts on.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)
    await service.cancel(seeded.run_id)
    await _wait_for_terminal(async_task_runner, task_id)

    view = await service.get(seeded.run_id)
    assert view.status is not RunStatus.FAILED
    assert view.status is RunStatus.INTERRUPTED
    assert view.error is not None

    gate.set()


async def test_the_status_is_written_before_cancel_returns(
    seed, make_run_service, async_task_runner, run_row
):
    """The trap this implementation exists to avoid.

    Recording the stop inside the worker's own `except CancelledError` is the
    natural way to write it, and there every later await can re-raise —
    including the write itself. The row is then left `running` and only
    `_reclaim` rescues it, with the wrong reason. `cancel` writes from the
    caller's task, so the row is correct the moment it returns, with no poll
    and no settling.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    await service.cancel(seeded.run_id)

    # Read straight from the row, with no wait in between.
    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.INTERRUPTED
    # `interrupted` is the one state a human moves out of, so nothing finished.
    assert run.finished_at is None

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)


async def test_stopping_one_run_leaves_the_next_model_to_execute(
    seed, make_run_service, async_task_runner, extractions_of
):
    """Stopping this run is not abandoning the evaluation.

    This is what the per-run `asyncio.Task` is for. Cancelling the job would
    take the models queued behind this one with it — and those are exactly the
    ones an analyst is still waiting on when they give up on this one.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate, gate_from=0)
    seeded = await seed(records=2, models=(DEFAULT_MODEL, SECOND_MODEL))
    first, second = seeded.run_ids
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    await service.cancel(first)
    # The second model is no longer gated, so it runs to completion.
    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)

    assert (await service.get(first)).status is RunStatus.INTERRUPTED
    assert (await service.get(second)).status is RunStatus.DONE
    assert len(await extractions_of(second)) == 2


async def test_stopping_a_queued_run_stops_it_before_the_worker_reaches_it(
    seed, make_run_service, async_task_runner, extractions_of
):
    """A run behind another model is `queued` and has no task yet.

    It is still the run an analyst can see and still the one they may decide
    not to wait for, so the verb has to work on it — and it has to prevent the
    execution rather than merely relabel a row the worker will overwrite when
    it gets there.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate, gate_from=0)
    seeded = await seed(records=2, models=(DEFAULT_MODEL, SECOND_MODEL))
    _first, second = seeded.run_ids
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    # The second has not started: the first is holding the worker.
    assert (await service.get(second)).status is RunStatus.QUEUED
    await service.cancel(second)

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)

    assert (await service.get(second)).status is RunStatus.INTERRUPTED
    assert await extractions_of(second) == []


async def test_a_stopped_run_resumes_from_the_hole(
    seed, make_run_service, async_task_runner, extractions_of, reporter
):
    """Stopping keeps the work, so Resume is a continuation and not a re-run.

    `UNIQUE (run_id, record_id)` is the resume key, and an analyst who stops a
    slow model at record 400 of 5 000 must not be made to pay for those 400
    again.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate, gate_from=2)
    seeded = await seed(records=5)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(3)
    await service.cancel(seeded.run_id)
    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)
    assert len(await extractions_of(seeded.run_id)) == 2

    resumed = make_run_service(FakeLLMClient(response=answer()))
    await resumed.execute_run(seeded.run_id, reporter)

    view = await resumed.get(seeded.run_id)
    assert view.status is RunStatus.DONE
    assert len(await extractions_of(seeded.run_id)) == 5


async def test_stopping_a_finished_run_is_refused(seed, make_run_service, reporter):
    """A Stop that silently succeeded on a run that had already finished would
    rewrite a `done` run's outcome as an interruption that never happened — an
    app inventing a result, which is the one thing this one may not do."""
    seeded = await seed(records=2)
    service = make_run_service(FakeLLMClient(response=answer()))
    await service.execute_run(seeded.run_id, reporter)
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE

    with pytest.raises(RunNotActiveError) as excinfo:
        await service.cancel(seeded.run_id)

    assert excinfo.value.status == RunStatus.DONE.value
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_stopping_a_run_that_does_not_exist_is_a_not_found(make_run_service):
    service = make_run_service(FakeLLMClient(response=answer()))

    with pytest.raises(NotFoundError):
        await service.cancel("no-such-run")
