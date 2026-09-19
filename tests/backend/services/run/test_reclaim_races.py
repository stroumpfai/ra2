"""`_reclaim` must never call a live run a dead one.

`_reclaim` runs on **every** read path — `progress`, `get`, `list_runs` — and
its whole test is "the row says `running` and this process does not claim it".
The Evaluation view's poll reaches those paths twice a tick for the length of a
run, so any instant in which the row says `running` and no claim is held is an
instant a poll lands in. What gets written then is not a hedge: it is
`_ERROR_INTERRUPTED_BY_RESTART`, *"the process died while this run was
executing"* — about a process that is fine, on a worker that carries on
extracting into a row now marked `interrupted`, offering an analyst a **Resume**
that would put a second worker on it.

There were two such instants, and neither is reachable by waiting: both are a
few microseconds wide, between one `await` and the next. So these tests do not
wait for the interleaving, they **construct** it. `make_run_service` takes a
`session_factory=` override, and `_HookedSessions` uses it to run a callback at
a chosen point inside the worker's own transactions — the one place from which
the gap is observable at all.

The two gaps:

- **Between the `running` write and the worker's claim.** `execute_run` called
  `_start` — which commits `queued -> running` — and claimed the run on the
  line after. A read in between reclaims it.
- **Between the worker releasing its claim and `cancel` recording the stop.**
  `Task.cancel()` only schedules; the worker unwinds through `execute_run`'s
  `finally` — dropping its own claim — while `cancel` is still awaiting, and the
  row says `running` throughout. A read there reclaims it, and
  `_finish_cancelled` re-reads the status before writing, so it then correctly
  declines to overwrite an outcome it did not produce. The stop an analyst
  asked for ends up on the row as a crash that never happened.

Asserted on the two error constants rather than on their wording: they are
stable identifiers, like `FindingCode`, and the sentence an analyst reads is
`ui/`'s business (CLAUDE.md, *findings, not prose*).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from tests.backend.services.run.conftest import answer
from tests.backend.services.run.test_in_flight import _wait_for_terminal
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.services.run_service import (
    _ERROR_CANCELLED,
    _ERROR_INTERRUPTED_BY_RESTART,
)

pytestmark = pytest.mark.backend


class _HookedSessions:
    """The seeded session factory, with a callback at a chosen moment.

    Two moments, because the two gaps are on opposite sides of a commit:
    `on_commit` fires immediately after a transaction commits — which is the
    instant `_start`'s `running` write becomes visible to every other session —
    and `on_open` fires as a transaction is opened, before its first read, which
    is where `_finish_cancelled` begins.

    Re-entrant by construction: the callbacks read through the same service, so
    they open sessions of their own. `_in_hook` stops that recursing.
    """

    def __init__(
        self,
        inner: Callable[[], Any],
        *,
        on_commit: Callable[[], Awaitable[None]] | None = None,
        on_open: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._on_commit = on_commit
        self._on_open = on_open
        self._in_hook = False
        #: Armed by the test at the moment the gap opens, so the hook does not
        #: also fire on the seeding and launch transactions before it.
        self.armed = False

    def __call__(self) -> _HookedSession:
        return _HookedSession(self._inner(), self)

    async def fire(self, which: str) -> None:
        hook = self._on_commit if which == "commit" else self._on_open
        if hook is None or not self.armed or self._in_hook:
            return
        self._in_hook = True
        try:
            await hook()
        finally:
            self._in_hook = False


class _HookedSession:
    """An `AsyncSession` that is itself, plus two callbacks.

    Everything not named here is delegated, so the repositories and
    `session_scope` see the session they expect.
    """

    def __init__(self, inner: Any, owner: _HookedSessions) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def __aenter__(self) -> _HookedSession:
        await self._inner.__aenter__()
        await self._owner.fire("open")
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._inner.__aexit__(*exc)

    async def commit(self) -> None:
        await self._inner.commit()
        await self._owner.fire("commit")


async def test_a_read_between_the_running_write_and_the_claim_does_not_kill_the_run(
    seed, make_run_service, async_task_runner, db_session_factory, run_row
):
    """The gap `execute_run` closed by claiming the run **before** `_start`.

    The hook runs a reclaiming read immediately after every commit, which
    includes the one that makes the run `running`. With the claim taken after
    `_start` returned, that read found a `running` row nobody claimed and wrote
    the process-death sentence about a worker that was about to extract its
    first record.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)

    seen: list[str | None] = []

    async def read_after_commit() -> None:
        # A reclaiming read, exactly as the Evaluation view's poll makes one.
        seen.append((await service.get(seeded.run_id)).error)

    hooked = _HookedSessions(db_session_factory, on_commit=read_after_commit)
    service = make_run_service(fake, task_runner=async_task_runner, session_factory=hooked)

    hooked.armed = True
    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)
    hooked.armed = False

    # The read did happen — otherwise this test proves nothing at all.
    assert seen, "no commit was observed between launch and the first extract"
    assert _ERROR_INTERRUPTED_BY_RESTART not in seen

    # And the worker is still executing a run the database still calls running.
    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.RUNNING

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_a_read_while_a_stop_is_being_recorded_does_not_relabel_it_a_crash(
    seed, make_run_service, async_task_runner, db_session_factory
):
    """The gap `cancel` closed with `_stopping`.

    The hook fires as `_finish_cancelled` opens its transaction, and does two
    things in the order that makes the gap: it lets the cancelled worker finish
    unwinding — which is where `execute_run`'s `finally` drops the worker's own
    claim, with the row still saying `running` — and only then makes the
    reclaiming read.

    Without `_stopping` that read relabels the run a process death, and
    `_finish_cancelled` then re-reads a status it is not allowed to overwrite
    and returns having written nothing. The analyst pressed Stop and the run
    says the process died.
    """
    gate = asyncio.Event()
    fake = FakeLLMClient(response=answer(), gate=gate)
    seeded = await seed(records=3)

    seen: list[str | None] = []

    async def read_after_the_worker_lets_go() -> None:
        # The worker is cancelled but not yet unwound: `Task.cancel()` only
        # schedules it. These yields are that unwind.
        for _ in range(10):
            await asyncio.sleep(0)
        seen.append((await service.get(seeded.run_id)).error)

    hooked = _HookedSessions(db_session_factory, on_open=read_after_the_worker_lets_go)
    service = make_run_service(fake, task_runner=async_task_runner, session_factory=hooked)

    task_id = await service.launch_runs(seeded.evaluation_id)
    await fake.wait_until_called(1)

    hooked.armed = True
    await service.cancel(seeded.run_id)
    hooked.armed = False

    assert seen, "no transaction was opened during the stop"
    assert _ERROR_INTERRUPTED_BY_RESTART not in seen

    # The durable record says what actually happened: somebody stopped it.
    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.error == _ERROR_CANCELLED

    gate.set()
    await _wait_for_terminal(async_task_runner, task_id)
