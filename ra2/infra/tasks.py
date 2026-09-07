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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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


class AsyncioTaskRunner:
    """The production runner: one in-process asyncio worker, no broker."""

    def __init__(self, ids: IdFactory) -> None:
        self._ids = ids

    def submit(self, name: str, work: TaskWork) -> TaskId:
        raise NotImplementedError

    def progress(self, task_id: TaskId) -> TaskProgress:
        raise NotImplementedError


class InlineTaskRunner:
    """Executes synchronously, so backend tests need no polling."""

    def __init__(self, ids: IdFactory) -> None:
        self._ids = ids

    def submit(self, name: str, work: TaskWork) -> TaskId:
        raise NotImplementedError

    def progress(self, task_id: TaskId) -> TaskProgress:
        raise NotImplementedError
