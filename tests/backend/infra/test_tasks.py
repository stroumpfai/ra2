"""The `TaskRunner` seam (sw-design.md §3, §9).

`InlineTaskRunner` must finish before `submit()` returns — no test using it
ever polls. `AsyncioTaskRunner` runs concurrently and reports progress that a
caller polls; that progress must never move backward on the way to a
terminal `ok`/`failed`.
"""

import asyncio

import pytest

from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import (
    AsyncioTaskRunner,
    InlineTaskRunner,
    ProgressReporter,
    TaskStatus,
)

pytestmark = pytest.mark.backend


def test_inline_task_runner_is_already_terminal_when_submit_returns() -> None:
    """No polling loop needed — the defining property of `InlineTaskRunner`."""
    runner = InlineTaskRunner(SeededFactory())
    seen: list[int] = []

    async def work(reporter: ProgressReporter) -> None:
        for done in (1, 2, 3):
            reporter.report(done, 3)
            seen.append(done)

    task_id = runner.submit("analyse", work)

    progress = runner.progress(task_id)
    assert progress.status is TaskStatus.OK
    assert progress.done == 3
    assert progress.total == 3
    assert seen == [1, 2, 3]


def test_inline_task_runner_records_a_failure_without_raising() -> None:
    """A failure is a recorded outcome, never a silent retry (§12.6's spirit)."""
    runner = InlineTaskRunner(SeededFactory())

    async def failing(reporter: ProgressReporter) -> None:
        reporter.report(1, 2)
        raise ValueError("boom")

    task_id = runner.submit("analyse", failing)

    progress = runner.progress(task_id)
    assert progress.status is TaskStatus.FAILED
    assert progress.error == "boom"


def test_inline_task_runner_ids_come_from_the_injected_factory() -> None:
    ids = SeededFactory()
    runner = InlineTaskRunner(ids)

    async def work(reporter: ProgressReporter) -> None:
        reporter.report(1, 1)

    task_id = runner.submit("analyse", work)
    # The id is whatever the very first call to a fresh, identically-seeded
    # factory produces — proof `submit()` mints through the injected
    # `IdFactory` rather than reaching for `uuid4()` itself (sw-design.md §3).
    assert task_id == SeededFactory().new_id()


async def test_asyncio_task_runner_reports_monotonic_progress_to_ok() -> None:
    runner = AsyncioTaskRunner(SeededFactory())
    ticks = 5

    async def work(reporter: ProgressReporter) -> None:
        for done in range(1, ticks + 1):
            await asyncio.sleep(0)
            reporter.report(done, ticks)

    task_id = runner.submit("analyse", work)

    observed_done: list[int] = []
    for _ in range(200):
        progress = runner.progress(task_id)
        observed_done.append(progress.done)
        if progress.is_terminal:
            break
        await asyncio.sleep(0)

    final = runner.progress(task_id)
    assert final.status is TaskStatus.OK
    assert final.done == ticks
    assert final.total == ticks
    # Never decreases, from PENDING's 0 all the way to the terminal value.
    assert observed_done == sorted(observed_done)


async def test_asyncio_task_runner_marks_failed_and_stops_progressing() -> None:
    runner = AsyncioTaskRunner(SeededFactory())

    async def failing(reporter: ProgressReporter) -> None:
        reporter.report(1, 4)
        await asyncio.sleep(0)
        raise RuntimeError("analyse blew up")

    task_id = runner.submit("analyse", failing)

    for _ in range(200):
        progress = runner.progress(task_id)
        if progress.is_terminal:
            break
        await asyncio.sleep(0)

    final = runner.progress(task_id)
    assert final.status is TaskStatus.FAILED
    assert final.error == "analyse blew up"


def test_progress_raises_for_an_unknown_task_id() -> None:
    runner = InlineTaskRunner(SeededFactory())
    with pytest.raises(KeyError):
        runner.progress("no-such-task")  # type: ignore[arg-type]
