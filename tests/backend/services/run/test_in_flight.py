"""A run observed **while it is running** — the harness's own proof.

Every other file in this directory asserts on a run that has already finished
or already failed, because `InlineTaskRunner` drives submitted work to
completion before `submit()` returns. That covers the outcomes and misses the
state a real run spends almost all of its life in: extracting a record, with
nothing committed yet.

That gap is not academic. On the reporting host a 9.7 B thinking model answers
one seeded record in ~130 s, so "running, `done == 0`" is what the Evaluation
screen shows for minutes at a stretch — and it was rendered as indistinguishable
from a dead worker precisely because no test at any layer had ever looked at it
(`plan-fix-evaluation-runs.md` §1.1 a).

So this file pins the three pieces that make such a test possible at all, and
is the acceptance test for Stage 0:

- `AsyncioTaskRunner` through `make_run_service(task_runner=…)`, so the work is
  a real `asyncio.Task` and `launch_runs` returns while it is still going;
- `FakeLLMClient(gate=…)`, so the worker can be held inside `extract` for as
  long as the assertions need;
- `FakeLLMClient.wait_until_called`, so the test synchronises on the worker
  having got there rather than guessing with `sleep`.

Stages 4 and 5 build their tests on exactly these three.
"""

import asyncio
import time
from typing import Final

import pytest
from tests.backend.services.run.conftest import answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import TaskId
from ra2.infra.tasks import AsyncioTaskRunner

pytestmark = pytest.mark.backend

#: The same patience `wait_until_called` uses. Long enough that a loaded CI
#: box does not fail on scheduling noise, short enough that a genuine deadlock
#: is reported rather than waited out.
_TIMEOUT_S: Final = 5.0
_POLL_S: Final = 0.01

#: Long enough to be measurable either side of a call, short enough to be free.
_DELAY_S: Final = 0.05


async def _wait_for_terminal(
    runner: AsyncioTaskRunner, task_id: TaskId, *, timeout_s: float = _TIMEOUT_S
) -> None:
    """Wait for a submitted job to reach `ok` or `failed`.

    Polled rather than awaited: `TaskRunner` deliberately exposes `progress()`
    and nothing else (sw-design.md SD7), and reaching past it for the
    `asyncio.Task` would be testing the runner's internals instead of its
    seam. Raises rather than hanging, for `wait_until_called`'s reason.
    """
    deadline = time.monotonic() + timeout_s
    while not runner.progress(task_id).is_terminal:
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"job {task_id} still {runner.progress(task_id).status} after {timeout_s}s"
            )
        await asyncio.sleep(_POLL_S)


async def test_a_gated_call_holds_the_run_running_with_nothing_committed(
    seed,
    make_run_service,
    async_task_runner,
    extractions_of,
):
    """The state the Evaluation screen could not describe: `running`, zero
    done, and a total that is already known."""
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    # Held inside the first `extract`. The run is started, its scope is known,
    # and not one row has been written.
    view = await service.progress(seeded.run_id)
    assert view.status is RunStatus.RUNNING
    assert (view.done, view.total) == (0, 3)
    assert await extractions_of(seeded.run_id) == []
    # And the run is **not** reclaimed while this process is executing it:
    # `progress()` reclaims runs left `running` by a dead process, and a live
    # one must survive that read (`run_service._reclaim`).
    assert fake.call_count == 1

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)

    view = await service.progress(seeded.run_id)
    assert view.status is RunStatus.DONE
    assert (view.done, view.total) == (3, 3)


async def test_a_delayed_call_takes_that_long(seed, make_run_service, reporter):
    """`delays` spends wall-clock time, where `latencies` only reports it.

    The distinction matters because `FrozenClock` makes `elapsed_ms` useless
    as evidence at this layer — a run that really took a second and one that
    pretended to are the same row. Wall clock is the only honest witness that
    a call was slow, so it is what is asserted.
    """
    seeded = await seed(records=1)
    service = make_run_service(FakeLLMClient(response=answer(), delays={0: _DELAY_S}))

    started = time.monotonic()
    await service.execute_run(seeded.run_id, reporter)
    elapsed_s = time.monotonic() - started

    assert elapsed_s >= _DELAY_S
    assert (await service.progress(seeded.run_id)).status is RunStatus.DONE


async def test_waiting_for_a_call_that_never_comes_fails_rather_than_hangs(
    seed, make_run_service, async_task_runner
):
    """A gated run that deadlocks must fail the test, not the suite.

    Without this the natural mistake — gating a call the worker never makes —
    hangs pytest until something kills it, with no output saying which test or
    why. The bound is the fixture's, and the message carries how far the
    worker actually got.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=1)
    service = make_run_service(fake, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    with pytest.raises(AssertionError, match="only 1 began"):
        await fake.wait_until_called(2, timeout_s=0.05)

    # Released so the worker is not left holding a task at teardown, where an
    # abandoned coroutine would surface as a warning in whichever test runs
    # next (`filterwarnings = ["error"]`).
    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)
