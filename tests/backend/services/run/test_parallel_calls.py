"""Records in flight within one run (sw-design.md §15.4, SD38).

`plan-parallel-calls.md` Stage 3. The worker keeps up to the run's pinned
`llm_parallel_calls` calls open at once. Everything else a run promises —
one record per transaction, no transaction across a call, holes for resume,
a bounded endpoint budget, Stop, a recorded failure — has to hold at any N.

Ordering is controlled with `ScriptedCalls` rather than with timing. Every
call is scripted by the order it **began**: answer, fail at the endpoint,
raise, or wait for the test to release it. A test that needs "these two calls
are still in flight when that one fails" says so with `held=`, and doesn't
depend on how fast a machine happens to commit.
"""

import asyncio
import time
from collections.abc import Collection, Mapping, Sequence
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.backend.services.run.conftest import DEFAULT_MODEL, answer
from tests.backend.services.run.test_in_flight import _wait_for_terminal
from tests.fixtures.fake_llm import DEFAULT_ENDPOINT, FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.llm import EndpointStatus, LlmEndpointError
from ra2.domain.llm import Extraction as LlmOutput
from ra2.persistence.models import Extraction

pytestmark = pytest.mark.backend

#: A second model tag from the catalogue fixtures, for the tests that need
#: one mapped model and one unmapped one in the same evaluation.
OTHER_MODEL: Final = "qwen2.5:14b-instruct-q6_K"

_TIMEOUT_S: Final = 5.0
_POLL_S: Final = 0.01


class ScriptedCalls:
    """An `LLMClient` whose calls are scripted by the order they began.

    **Every test that holds calls releases them in a `finally`, and waits
    there for the run to end.** A run still going when the test's loop and
    database are torn down hangs the suite instead of failing the test.

    - `held`: these calls wait on `release` before doing anything else;
    - `fail`: these raise the endpoint error the real adapter raises;
    - `raise_at`: these raise the given exception instead;
    - every other call answers through `inner`.

    It also counts what a pool test needs to see: calls in flight per model
    and their peak, and how many calls were cancelled while open.
    """

    def __init__(
        self,
        *,
        inner: FakeLLMClient | None = None,
        held: Collection[int] = (),
        fail: Collection[int] = (),
        raise_at: Mapping[int, BaseException] | None = None,
        hold_s: float = 0.0,
    ) -> None:
        self.release = asyncio.Event()
        self._inner = inner or FakeLLMClient(response=answer())
        self._held = frozenset(held)
        self._fail = frozenset(fail)
        self._raise_at = dict(raise_at or {})
        self._hold_s = hold_s
        self._current: dict[str, int] = {}
        self.calls = 0
        self.cancelled = 0
        self.peak: dict[str, int] = {}

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
        reasoning_effort: str | None = None,
    ) -> LlmOutput[T]:
        index = self.calls
        self.calls += 1
        self._current[model] = self._current.get(model, 0) + 1
        self.peak[model] = max(self.peak.get(model, 0), self._current[model])
        try:
            if index in self._held:
                await self.release.wait()
            elif self._hold_s:
                # Long enough for sibling workers to be in flight at once, so
                # a peak of N is a peak that was reachable, not an accident.
                await asyncio.sleep(self._hold_s)
            if index in self._raise_at:
                raise self._raise_at[index]
            if index in self._fail:
                raise LlmEndpointError(DEFAULT_ENDPOINT, EndpointStatus.UNREACHABLE)
            return await self._inner.extract(
                text,
                schema,
                model,
                temperature=temperature,
                seed=seed,
                reasoning_effort=reasoning_effort,
            )
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self._current[model] -= 1

    async def wait_until_called(self, count: int, *, timeout_s: float = _TIMEOUT_S) -> None:
        """`FakeLLMClient.wait_until_called`'s contract: entry, not
        completion, and a bounded wait that fails rather than hangs."""
        deadline = time.monotonic() + timeout_s
        while self.calls < count:
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"waited {timeout_s}s for call {count}; only {self.calls} began"
                )
            await asyncio.sleep(_POLL_S)


def _engine(db_session_factory: async_sessionmaker[AsyncSession]) -> AsyncEngine:
    bind = db_session_factory.kw["bind"]
    assert isinstance(bind, AsyncEngine)
    return bind


async def test_parallel_calls_keeps_exactly_n_calls_in_flight(
    seed, make_run_service, async_task_runner, extractions_of
):
    """N=3: three calls held open at once, never a fourth, and all six
    records extracted once the three are released."""
    client = ScriptedCalls(held=range(100))
    seeded = await seed(records=6, parallel_calls=3)
    service = make_run_service(client, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    try:
        await client.wait_until_called(3)
        with pytest.raises(AssertionError, match="only 3 began"):
            await client.wait_until_called(4, timeout_s=0.1)
    finally:
        client.release.set()
        await _wait_for_terminal(async_task_runner, task_id)

    assert client.peak == {DEFAULT_MODEL: 3}
    assert client.calls == 6
    assert len(await extractions_of(seeded.run_id)) == 6
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_an_unmapped_model_runs_serially(seed, make_run_service):
    """One evaluation, two models, only one of them pinned above 1. The pin
    is per run, so the second model is asked one record at a time.

    Ceilings, not exact peaks: whether sibling calls overlap inside a sleep
    depends on machine load, and that N is *reached* is
    `test_parallel_calls_keeps_exactly_n_calls_in_flight`'s job, done with
    held calls rather than timing. A 50 ms hold makes a wrong ceiling show.
    """
    client = ScriptedCalls(hold_s=0.05)
    seeded = await seed(
        records=6, models=(DEFAULT_MODEL, OTHER_MODEL), parallel_calls={DEFAULT_MODEL: 3}
    )
    service = make_run_service(client)

    await service.launch_runs(seeded.evaluation_id)

    assert client.peak[DEFAULT_MODEL] <= 3
    assert client.peak[OTHER_MODEL] == 1
    for run_id in seeded.run_ids:
        assert (await service.get(run_id)).status is RunStatus.DONE


@pytest.mark.parametrize("parallel_calls", [1, 3])
async def test_no_transaction_spans_a_model_call(
    parallel_calls, seed, make_run_service, async_task_runner, db_session_factory
):
    """Replaces the N=1-only form of this property for any N (§15.3).

    With every worker held inside `extract`, no worker can be resolving or
    committing, so any connection checked out of the pool at that moment
    would be a session held open across a call. There must be none.
    `test_each_record_is_committed_before_the_next_model_call` keeps the
    stricter serial form at N=1.
    """
    client = ScriptedCalls(held=range(100))
    seeded = await seed(records=parallel_calls * 2, parallel_calls=parallel_calls)
    service = make_run_service(client, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    try:
        await client.wait_until_called(parallel_calls)
        assert _engine(db_session_factory).pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        client.release.set()
        await _wait_for_terminal(async_task_runner, task_id)
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_parallel_and_serial_runs_store_identical_values(
    seed, make_run_service, extractions_of
):
    """This tests the code, not the model: with a deterministic client, a run
    at 3 and a run at 1 store the same values for the same records, whatever
    order the three workers committed in. Stage 0b measured the model."""
    seeded = await seed(
        records=7, models=(DEFAULT_MODEL, OTHER_MODEL), parallel_calls={DEFAULT_MODEL: 3}
    )
    inner = FakeLLMClient(
        responses={
            marker: answer(weather=f"0{i % 3 + 1}", note=f"note {i}", evidence=f"span {i}")
            for i, marker in enumerate(seeded.markers)
        }
    )
    service = make_run_service(ScriptedCalls(inner=inner, hold_s=0.005))

    await service.launch_runs(seeded.evaluation_id)

    def stored(rows: Sequence[Extraction]) -> set[tuple[object, ...]]:
        return {
            (
                row.record_id,
                value.feature_id,
                value.value_raw,
                value.present_flag,
                value.evidence_span,
            )
            for row in rows
            for value in row.values
        }

    parallel = await extractions_of(seeded.run_ids[0])
    serial = await extractions_of(seeded.run_ids[1])
    assert len(parallel) == len(serial) == 7
    assert stored(parallel) == stored(serial)
    assert {value[2] for value in stored(parallel)} >= {"note 0", "note 6"}


async def test_endpoint_budget_stops_dispatch_and_lets_in_flight_calls_commit(
    seed, make_run_service, async_task_runner, extractions_of
):
    """N=3, ten records. Calls 1 and 2 are held open. Call 0 answers, so the
    budget is 3, and the one free worker then fails three in a row (calls 3–5)
    and trips it. No seventh call starts. Released, call 1 fails and call 2
    answers and **commits**: an answer already on its way is kept, not thrown
    away because a sibling gave up. Two calls ran past the trip, which is N−1.
    """
    client = ScriptedCalls(held={1, 2}, fail={1, 3, 4, 5})
    seeded = await seed(records=10, parallel_calls=3)
    service = make_run_service(client, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    try:
        await client.wait_until_called(6)
        with pytest.raises(AssertionError, match="only 6 began"):
            await client.wait_until_called(7, timeout_s=0.1)
    finally:
        client.release.set()
        await _wait_for_terminal(async_task_runner, task_id)

    assert client.calls == 6
    assert len(await extractions_of(seeded.run_id)) == 2
    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.error is not None
    assert view.error.startswith("interrupted with 8 record(s) not extracted")
    # Counted, including the one that failed after the trip.
    assert "4 records failed at the endpoint" in view.error


async def test_cancel_cancels_every_in_flight_call(
    seed, make_run_service, async_task_runner, extractions_of, reporter
):
    """N=3: two records answer and commit, then three calls are held open
    and the run is stopped. All three see the cancellation, the two rows
    stay, and Resume finishes the run from the holes."""
    client = ScriptedCalls(held=range(2, 100))
    seeded = await seed(records=6, parallel_calls=3)
    service = make_run_service(client, task_runner=async_task_runner)

    task_id = await service.launch_runs(seeded.evaluation_id)
    try:
        await client.wait_until_called(5)
        await service.cancel(seeded.run_id)
    finally:
        # A no-op once the calls are cancelled; without it, a failure above
        # would leave them holding the loop and hang teardown, not fail.
        client.release.set()
        await _wait_for_terminal(async_task_runner, task_id)

    assert client.cancelled == 3
    assert len(await extractions_of(seeded.run_id)) == 2
    assert (await service.get(seeded.run_id)).status is RunStatus.INTERRUPTED

    resumed = make_run_service(FakeLLMClient(response=answer()))
    await resumed.execute_run(seeded.run_id, reporter)

    assert (await resumed.get(seeded.run_id)).status is RunStatus.DONE
    assert len(await extractions_of(seeded.run_id)) == 6


async def test_an_unexpected_failure_cancels_siblings_and_fails_the_run(
    seed, make_run_service, reporter, extractions_of, run_row
):
    """A bug in one worker is a bug in the run. Calls 1 and 2 are held open,
    call 0 answers, and call 3 raises something that isn't an endpoint
    failure. The two held calls are cancelled, the run is `failed` with that
    error, and the committed row stays (§10.4)."""
    client = ScriptedCalls(held={1, 2}, raise_at={3: RuntimeError("boom")})
    seeded = await seed(records=6, parallel_calls=3)
    service = make_run_service(client)

    # Bounded: nothing releases the held calls, so a pool that never reached
    # call 3 would otherwise wait on them forever instead of failing.
    with pytest.raises(RuntimeError, match="boom"):
        async with asyncio.timeout(_TIMEOUT_S):
            await service.execute_run(seeded.run_id, reporter)

    assert client.cancelled == 2
    assert len(await extractions_of(seeded.run_id)) == 1
    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.FAILED
    assert run.error is not None
    assert "boom" in run.error


async def test_resume_runs_at_the_pinned_parallelism(
    seed, make_run_service, backend_settings, set_run_status
):
    """The run was launched at 2. The map now says 4. Resume executes at 2:
    one run's rows never mix two latency regimes (SD38). At most two in flight
    — a ceiling, for the reason the unmapped-model test gives."""
    client = ScriptedCalls(hold_s=0.05)
    seeded = await seed(records=8, parallel_calls=2)
    await set_run_status(seeded.run_id, RunStatus.INTERRUPTED)
    settings = backend_settings.model_copy(update={"llm_parallel_calls": {DEFAULT_MODEL: 4}})
    service = make_run_service(client, settings=settings)

    await service.resume(seeded.run_id)

    assert client.peak[DEFAULT_MODEL] <= 2
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_the_run_start_log_line_names_the_parallelism(
    seed, make_run_service, reporter, caplog
):
    """`parallel=N` beside `timeout=`: both decide how long the next line can
    take, because a call past what Ollama serves at once waits in its queue."""
    seeded = await seed(records=2, parallel_calls=2)
    service = make_run_service(FakeLLMClient(response=answer()))

    with caplog.at_level("INFO", logger="ra2.services.run_service"):
        await service.execute_run(seeded.run_id, reporter)

    assert any("parallel=2" in record.getMessage() for record in caplog.records)
