# FROZEN (protocols) — see CONTRACTS.md
"""The `TaskRunner` seam — the in-process asyncio worker (sw-design.md §9, SD7).

Phase 1 uses it for **analyse** and **freeze**, with progress polled by the UI
through `GET /api/v1/tasks/{id}`. mvp-spec.md §9 extends the same seam to
extraction runs, which additionally persist to the `run` table and must be
restart-safe — so the shape is settled here, once.

No Redis, no Celery (mvp-spec.md §3).

A4 implements `AsyncioTaskRunner` (real, concurrent) and `InlineTaskRunner`
(executes synchronously, so backend tests need no polling).
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ra2.domain.ids import TaskId
from ra2.infra.idgen import IdFactory

__all__ = [
    "AsyncioTaskRunner",
    "InlineTaskRunner",
    "ProgressReporter",
    "TaskProgress",
    "TaskRunner",
    "TaskStatus",
    "TaskWork",
]


class TaskStatus(StrEnum):
    """`OK` and `FAILED` are terminal; nothing leaves them."""

    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """What `GET /api/v1/tasks/{id}` returns and what the UI renders.

    `done`/`total` drive the records-done/total and ETA display (mvp-spec.md §9).
    `total` is 0 while the work has not yet counted its units.
    """

    task_id: TaskId
    name: str
    status: TaskStatus
    done: int = 0
    total: int = 0
    message: str = ""
    #: Set only when `status` is `FAILED`. A failure is a recorded outcome,
    #: never a silent retry.
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.OK, TaskStatus.FAILED)


@runtime_checkable
class ProgressReporter(Protocol):
    """Handed to the running coroutine so it can report without knowing the
    runner."""

    def report(self, done: int, total: int, message: str = "") -> None: ...


#: The unit of work `submit` takes. It receives a reporter and returns nothing;
#: results are persisted by the work itself, not returned through the runner.
type TaskWork = Callable[[ProgressReporter], Awaitable[None]]


@runtime_checkable
class TaskRunner(Protocol):
    """Submit work, poll progress. That is the whole surface."""

    def submit(self, name: str, work: TaskWork) -> TaskId:
        """Schedule `work` and return its id immediately."""
        ...

    def progress(self, task_id: TaskId) -> TaskProgress:
        """Current progress. Raises `KeyError` for an unknown id."""
        ...


# --- STUB implementations — bodies owned by A4 (feat/m2-infra). Not frozen. ---


class _ProgressTable:
    """Shared bookkeeping for both runners.

    Guarantees the monotonic-progress invariant itself — `update()` never
    lets `done` move backward and a terminal task never moves again — rather
    than trusting every `TaskWork` to behave.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[TaskId, TaskProgress] = {}

    def create(self, task_id: TaskId, name: str) -> None:
        with self._lock:
            self._tasks[task_id] = TaskProgress(
                task_id=task_id, name=name, status=TaskStatus.PENDING
            )

    def mark_running(self, task_id: TaskId) -> None:
        with self._lock:
            current = self._tasks[task_id]
            if current.is_terminal:
                return
            self._tasks[task_id] = replace(current, status=TaskStatus.RUNNING)

    def update(self, task_id: TaskId, *, done: int, total: int, message: str) -> None:
        with self._lock:
            current = self._tasks[task_id]
            if current.is_terminal:
                return
            self._tasks[task_id] = replace(
                current,
                status=TaskStatus.RUNNING,
                done=max(done, current.done),
                total=total or current.total,
                message=message,
            )

    def mark_ok(self, task_id: TaskId) -> None:
        with self._lock:
            current = self._tasks[task_id]
            done = current.total if current.total else current.done
            self._tasks[task_id] = replace(
                current, status=TaskStatus.OK, done=done, total=current.total or done
            )

    def mark_failed(self, task_id: TaskId, error: str) -> None:
        with self._lock:
            current = self._tasks[task_id]
            self._tasks[task_id] = replace(current, status=TaskStatus.FAILED, error=error)

    def get(self, task_id: TaskId) -> TaskProgress:
        with self._lock:
            return self._tasks[task_id]


class _Reporter:
    """The `ProgressReporter` handed to running work."""

    def __init__(self, task_id: TaskId, table: _ProgressTable) -> None:
        self._task_id = task_id
        self._table = table

    def report(self, done: int, total: int, message: str = "") -> None:
        self._table.update(self._task_id, done=done, total=total, message=message)


class AsyncioTaskRunner:
    """The production runner: one in-process asyncio worker, no broker."""

    def __init__(self, ids: IdFactory) -> None:
        self._ids = ids
        self._table = _ProgressTable()
        #: Kept only so the tasks are not garbage-collected mid-flight.
        self._tasks: dict[TaskId, asyncio.Task[None]] = {}

    def submit(self, name: str, work: TaskWork) -> TaskId:
        task_id = TaskId(self._ids.new_id())
        self._table.create(task_id, name)
        reporter = _Reporter(task_id, self._table)

        async def _run() -> None:
            self._table.mark_running(task_id)
            try:
                await work(reporter)
            except Exception as exc:  # a failure is a recorded outcome, never a silent retry
                self._table.mark_failed(task_id, str(exc))
            else:
                self._table.mark_ok(task_id)

        loop = asyncio.get_running_loop()
        self._tasks[task_id] = loop.create_task(_run())
        return task_id

    def progress(self, task_id: TaskId) -> TaskProgress:
        return self._table.get(task_id)


class InlineTaskRunner:
    """Executes synchronously, so backend tests need no polling.

    `submit()` is not an `async def` — the `TaskRunner` protocol calls for a
    plain method that schedules work and returns immediately. To still run an
    async `TaskWork` to *completion* before returning (so `progress()` is
    already terminal), the work is driven on a brand-new event loop in a
    throwaway thread and joined: `submit()` may itself be called from inside
    a running loop (a service coroutine calling it without `await`), and
    neither `asyncio.run()` nor `loop.run_until_complete()` can re-enter a
    loop that is already running on the calling thread.
    """

    def __init__(self, ids: IdFactory) -> None:
        self._ids = ids
        self._table = _ProgressTable()

    def submit(self, name: str, work: TaskWork) -> TaskId:
        task_id = TaskId(self._ids.new_id())
        self._table.create(task_id, name)
        self._table.mark_running(task_id)
        reporter = _Reporter(task_id, self._table)

        errors: list[Exception] = []

        def _run_to_completion() -> None:
            try:
                asyncio.run(work(reporter))
            except Exception as exc:  # recorded as TaskStatus.FAILED below
                errors.append(exc)

        worker = threading.Thread(target=_run_to_completion)
        worker.start()
        worker.join()

        if errors:
            self._table.mark_failed(task_id, str(errors[0]))
        else:
            self._table.mark_ok(task_id)

        return task_id

    def progress(self, task_id: TaskId) -> TaskProgress:
        return self._table.get(task_id)
