# STUB — bodies owned by I3 (feat/p3-run-service). Not frozen.
"""The run worker (sw-design.md §15.4, mvp-spec.md §9/§10, N6).

The `TaskRunner` seam (SD7) with a persistent tail — one submitted job per
`run`, `ProgressReporter` for the UI, and the `run` / `extraction` tables for
everything that has to survive the process. `GET /api/v1/tasks/{id}` (§9) is
unchanged; the UI polls it with `ui.timer` exactly as Import does. No
streaming, no websocket push.

Five properties this module exists to guarantee:

- **One record, one transaction.** One `extraction` row, its
  `extraction_value` children and its `extraction_entity` children are
  committed together, per record. Nothing batches across records, and nothing
  holds a transaction open across an LLM call. This is what makes N6's
  restart-safety true rather than aspirational, and it is the one thing in
  this file that is not negotiable under time pressure (plan-phase-3.md R3).
- **Serial.** One model at a time, `RA2_RUN_CONCURRENCY` defaulting to 1: the
  GPU is the bottleneck and it is what the design draws.
- **Retries bounded and counted**, never a retry-until-quiet loop. The count
  is carried back on the `Extraction` and rendered in the metrics line.
- **Provenance written at run start**, not at completion — a run that dies
  mid-corpus is still a reproducible run (mvp-spec.md §19.8).
- **A read never writes a status.** `progress`, `get` and `list_runs` report;
  they do not decide. The one method that relabels a run it did not execute is
  `reclaim_orphans`, and it is called once, from `main.py`'s lifespan, where a
  `running` row is stale unconditionally because this process is executing
  nothing yet. Reclaiming on the read paths instead — which this replaced —
  meant deciding at moments when the answer could be wrong, against an
  in-memory claim that moved on a different schedule from the row, and the
  Evaluation view asks twice a tick for the length of a run.

`PromptResolver` (`services/protocols.py`) is why this module never imports
`prompt_service`, and the injected `LLMClient` is why it never imports
`openai`.

---

## The two shapes a record can fail in

H4's adapter draws the line and this module keeps it (sw-design.md §15.3):

- **A bad response is a datum.** `extract` returns an `Extraction` with
  `parse_ok=False` and `raw_output_text` verbatim; the row is written and the
  run continues. A parse failure is never retried — temperature and seed are
  fixed, so the retry returns the same bytes.
- **An endpoint that will not answer after its bounded retries raises.** No
  row is written, which leaves exactly the mid-corpus hole
  `pending_record_ids` is specified to find. Writing a placeholder row for it
  would destroy resume, so nothing here does.
"""

import asyncio
import json
import logging
import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import (
    EvaluationSize,
    ParsedExtraction,
    ParseFailure,
    RunStatus,
    build_output_schema,
    parse_output,
)
from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    ExtractionId,
    FeatureId,
    RecordId,
    RunId,
    TaskId,
)
from ra2.domain.llm import Extraction as LlmOutput
from ra2.domain.llm import LLMClient, LlmEndpointError
from ra2.domain.prompt import FeatureBlockEntry
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuProbe
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import ProgressReporter, TaskRunner
from ra2.persistence.models import (
    Evaluation,
    EvaluationFeature,
    Extraction,
    ExtractionEntity,
    ExtractionValue,
    Feature,
    Run,
)
from ra2.persistence.repositories.evaluation_repo import EvaluationRepository
from ra2.persistence.repositories.extraction_repo import ExtractionRepository
from ra2.persistence.repositories.run_repo import RunRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import FeatureValidationError, NotFoundError, RunNotActiveError
from ra2.services.feature_service import matching_rule_from_json
from ra2.services.protocols import PromptResolver
from ra2.services.readmodels import Page, RunProgressView, RunView, SortDir

__all__ = ["RunService", "run_ordinals"]

#: A run is the one thing this app does that takes longer than a screen can
#: hold attention — minutes per record, tens of minutes end to end — and until
#: `infra/logging.py` it reported nothing at all while it worked. Every line
#: below is bounded by that module's rule: **ids, counts, statuses, model tags
#: and durations, never anything that came out of a delivery.** The resolved
#: prompt and `response.raw_output_text` are in scope at several of these call
#: sites; neither is ever an argument to one.
_log = logging.getLogger(__name__)

#: `sort_key` -> the `RunView` attribute it sorts on. An unknown key falls
#: back to `started_at`, the runs table's own default (sw-design.md §8.1.4).
_SORT_KEYS: Final[frozenset[str]] = frozenset({"started_at", "model_tag", "status", "records_done"})

#: How many records in a row may fail at the endpoint before the worker stops
#: asking, **once this run has committed at least one row**. One failure is a
#: **record**'s problem and leaves a hole the resume query finds; three in a
#: row is the **endpoint**'s problem, and grinding a 5 000-record corpus
#: through `RA2_LLM_TIMEOUT_S` apiece to discover that would be neither honest
#: nor bounded. The run is left `interrupted` either way, which is the state
#: Resume acts on (§15 F8). Deliberately not a setting: it is a property of
#: "the endpoint is down", not a knob an analyst has any basis to turn.
_MAX_CONSECUTIVE_ENDPOINT_ERRORS: Final = 3

#: The same bound **before** this run has committed anything — one failure,
#: and stop.
#:
#: Three in a row is the right tolerance for an endpoint that has demonstrably
#: worked: it has answered for this run, with this model, this prompt and this
#: schema, so a failure now is plausibly transient and worth another ask.
#: Nothing supports that reading on a run that has never produced a row. There
#: the first failure is the *only* evidence there is, and it says the
#: configuration does not work — a verdict, not a flake.
#:
#: The arithmetic is why it matters. An `LlmEndpointError` reaching this
#: module means the adapter already exhausted its own bounded retries, so each
#: of these records has cost up to `RA2_LLM_TIMEOUT_S` — 600 s since the bound
#: was measured against a reasoning model (`Settings.llm_timeout_s`). Three of
#: them is half an hour to be told something the first one already said.
#:
#: Counted over the run, not over this execution: a resume of a run that has
#: rows gets the full tolerance, because those rows are the evidence. A resume
#: of a run that has none does not, because it has none.
_MAX_ENDPOINT_ERRORS_BEFORE_FIRST_ROW: Final = 1

#: `extraction.parse_error` when the *adapter* already judged the response
#: unreadable (`Extraction.parse_ok is False`) but named no reason. A stable
#: identifier, like `domain.extraction`'s own reasons — asserted on, never
#: rendered as prose.
_REASON_ADAPTER_PARSE_FAILED: Final = "adapter_parse_failed"

#: `run.error` on a run this process found still marked `running` although
#: nothing is executing it — the process died under it (§15.4). Relabelling is
#: all that happens: **nothing auto-restarts** (§15 F8).
_ERROR_INTERRUPTED_BY_RESTART: Final = "interrupted: the process died while this run was executing"

#: `run.error` on a run a person stopped. `interrupted` and not a status of
#: its own: the state is already exactly right — partial work kept, nothing
#: auto-restarted, Resume the one way out — and `run.status` is an
#: unconstrained `String(16)`, so a new member would have been free and still
#: wrong. What differs is *why*, and `run.error` is where this codebase
#: already keeps that (`_ERROR_INTERRUPTED_BY_RESTART`, beside it).
_ERROR_CANCELLED: Final = "interrupted: stopped before it finished"

#: The two statuses a run can be stopped **out of**. The same pair
#: `lifecycle_service.ACTIVE_STATUSES` refuses a discard for, from the other
#: side: a worker is writing to these and to no others.
_CANCELLABLE_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {RunStatus.QUEUED, RunStatus.RUNNING}
)

#: M0-D8's serialisation convention, key-sorted like every other JSON this
#: codebase writes.
_JSON_KWARGS: Final[Mapping[str, object]] = {
    "sort_keys": True,
    "separators": (",", ":"),
    "ensure_ascii": False,
}


@dataclass(frozen=True, slots=True)
class _RunPlan:
    """Everything one run needs, read **once** before the record loop.

    Read up front on purpose: the per-record transaction must carry nothing
    but the write itself, and re-reading the feature snapshot 5 000 times
    would put a query between every LLM call and the commit it belongs to.
    Nothing in here can change mid-run — an evaluation is immutable after
    launch (sw-design.md §15.2).
    """

    run_id: RunId
    evaluation_id: EvaluationId
    corpus_id: CorpusId
    model_name: str
    temperature: float
    seed: int
    #: The dev cap (`RA2_DEV_RECORD_MAX`), or `None` for the whole corpus.
    limit: int | None
    features: tuple[FeatureBlockEntry, ...]
    #: `feature key -> FeatureId`, for the `extraction_value` rows.
    feature_ids: Mapping[str, FeatureId]
    #: `feature key -> the snapshot's codes`, for `parse_output`.
    enum_codelists: Mapping[str, frozenset[str]]
    #: The constrained-decoding format, built once so two records of one run
    #: cannot be asked a differently-ordered question (§15.3).
    schema: type[BaseModel]


class _OffsetReporter:
    """A `ProgressReporter` that reports one run's progress as part of a job
    covering several.

    Runs execute serially (§15 F7), so the job's progress is "records done
    across every run in it" — `done` from earlier runs is a fixed base and the
    total is the whole job's. Both numbers still come from committed rows; the
    offset is arithmetic on derived counts, not a counter.
    """

    def __init__(self, inner: ProgressReporter, *, base: int, total: int) -> None:
        self._inner = inner
        self._base = base
        self._total = total

    def report(self, done: int, total: int, message: str = "") -> None:
        self._inner.report(self._base + done, self._total, message)


class RunService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: LLMClient,
        prompt_resolver: PromptResolver,
        gpu_probe: GpuProbe,
        task_runner: TaskRunner,
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._llm_client = llm_client
        self._prompt_resolver = prompt_resolver
        self._gpu_probe = gpu_probe
        self._task_runner = task_runner
        self._clock = clock
        self._ids = ids
        self._settings = settings
        #: The `asyncio.Task` executing each run, so `cancel` can stop **one**
        #: of them. A job covers every run of an evaluation and executes them
        #: serially, so without a task per run "stop this run" could only be
        #: spelled "abandon the evaluation".
        self._tasks: dict[RunId, asyncio.Task[None]] = {}
        #: Runs somebody has asked to stop. Two jobs: it tells a cancellation
        #: *we* asked for apart from the whole job being torn down — both
        #: arrive as `CancelledError` at the same await — and it lets a run
        #: still queued behind another be skipped when the worker reaches it.
        self._cancel_requested: set[RunId] = set()

    # -----------------------------------------------------------------------
    # Submitting work
    # -----------------------------------------------------------------------

    async def launch_runs(self, evaluation_id: EvaluationId) -> TaskId:
        """Submit the `queued` runs `EvaluationService.launch` created.

        One `TaskRunner` job for the evaluation, executing its runs
        **serially** — `RA2_RUN_CONCURRENCY` is 1 and nothing in this phase
        raises it. Returns the task id the UI polls.

        :raises NotFoundError: no such evaluation.
        """
        async with self._session_factory() as session:
            evaluation = await EvaluationRepository(session).get(evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            run_ids = [
                RunId(run.id)
                for run in sorted(evaluation.runs, key=lambda r: r.id)
                if RunStatus(run.status) is RunStatus.QUEUED
            ]
        return self._submit(f"runs:{evaluation_id}", run_ids)

    async def resume(self, run_id: RunId) -> TaskId:
        """Pick an `interrupted` run back up. **Explicit, never automatic.**

        Resume is "the record ids in this run's scope with no `extraction`
        row" — `UNIQUE (run_id, record_id)` *is* the resume key. The set can
        have **holes in the middle**, not just a missing tail: a record whose
        retries were exhausted leaves one.

        N6 asks for restart-*safe* and resumable, which this is; it does not
        ask for automatic, and a run that restarts itself whenever the app
        starts burns GPU hours on work the user may have abandoned (§15 F8).

        A run with nothing pending is not an error: it finishes immediately as
        `done`, which is the truth about it.

        :raises NotFoundError: no such run.
        """
        async with self._session_factory() as session:
            if await RunRepository(session).get(run_id) is None:
                raise NotFoundError("run", run_id)
        return self._submit(f"resume:{run_id}", [run_id])

    def _submit(self, name: str, run_ids: Sequence[RunId]) -> TaskId:
        """One job, however many runs — the UI polls one task id."""
        ordered = tuple(run_ids)

        async def work(reporter: ProgressReporter) -> None:
            await self._execute_serially(ordered, reporter)

        return self._task_runner.submit(name, work)

    async def _execute_serially(self, run_ids: Sequence[RunId], reporter: ProgressReporter) -> None:
        """One model at a time (§15 F7). `RA2_RUN_CONCURRENCY` is read here so
        raising it is a config line rather than a rewrite — phase 3 never
        does, and anything above 1 is refused rather than silently ignored."""
        if self._settings.run_concurrency != 1:
            raise NotImplementedError(
                "RA2_RUN_CONCURRENCY > 1 is not implemented in this phase (sw-design.md §15.4)"
            )
        totals: list[int] = []
        for run_id in run_ids:
            done, pending = await self._counts(run_id)
            totals.append(done + pending)
        grand_total = sum(totals)

        base = 0
        for run_id in run_ids:
            if run_id in self._cancel_requested:
                # Stopped while still queued behind another model. `cancel`
                # has already written the row; there is nothing to execute and
                # nothing to record.
                self._cancel_requested.discard(run_id)
                continue
            await self._execute_cancellably(
                run_id, _OffsetReporter(reporter, base=base, total=grand_total)
            )
            # Advanced by what actually committed, not by the scope size: a
            # run that ends `interrupted` leaves the job's bar short of 100 %,
            # which is the honest picture of it.
            base += await self._count_done(run_id)

    async def _execute_cancellably(self, run_id: RunId, reporter: ProgressReporter) -> None:
        """One model's pass, as its own `asyncio.Task`.

        The task exists so `cancel` has something to cancel that is **this
        run** and not the job around it. A job covers every run of an
        evaluation, so cancelling at job level would make "stop this run" mean
        "abandon the evaluation" — and the runs after it are exactly the ones
        an analyst is still waiting on when they give up on this one.

        `self._cancel_requested` is what tells the two cancellations apart.
        Stopping this run and tearing down the whole job both arrive here as a
        `CancelledError` from the same await, and `task.cancelled()` is true in
        both: cancelling the outer task cancels the future it is waiting on,
        which is this task. Only the recorded *intent* distinguishes them, so
        an unasked-for cancellation propagates and ends the job.
        """
        task = asyncio.create_task(self.execute_run(run_id, reporter))
        self._tasks[run_id] = task
        try:
            await task
        except asyncio.CancelledError:
            if run_id not in self._cancel_requested:
                raise
            self._cancel_requested.discard(run_id)
        finally:
            self._tasks.pop(run_id, None)

    async def cancel(self, run_id: RunId) -> None:
        """Stop a run somebody has decided not to wait for.

        Real task cancellation, not a flag the record loop checks: the worker
        spends almost all of its time inside one `LLMClient.extract` call, and
        on a model answering a record in minutes a cooperative stop would take
        until the end of the current record to take effect. Escaping exactly
        that wait is the point of the verb.

        **The status is written here, in the caller's task**, rather than in
        the worker's own `except CancelledError` handler, and that is the whole
        trick. A cancelled task can have `CancelledError` re-raised at any
        later await inside it — including the write that records why it
        stopped — so a handler that finishes the row there needs
        `asyncio.shield` and still cannot promise the write landed before this
        call returns. This task was never cancelled, so its write is ordinary.
        It is also ordered: `Task.cancel()` only *schedules* the cancellation,
        so the worker unwinds during the await below and cannot commit
        anything after it.

        The run stays `interrupted` — see `_ERROR_CANCELLED`. Whatever it
        managed to extract is kept and Resume picks it up from the hole, which
        is the behaviour an analyst stopping a slow model wants rather than
        losing the hour it already spent.

        :raises NotFoundError: no such run.
        :raises RunNotActiveError: the run is not `queued` or `running`.
        """
        async with self._session_factory() as session:
            run = await RunRepository(session).get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            status = RunStatus(run.status)
        if status not in _CANCELLABLE_STATUSES:
            raise RunNotActiveError(str(run_id), status.value)

        self._cancel_requested.add(run_id)
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
        await self._finish_cancelled(run_id)

    async def _finish_cancelled(self, run_id: RunId) -> None:
        """Record the stop — **unless the run finished on its own first**.

        The status is re-read inside the write's own transaction because the
        two are not one atomic step: a run can reach `done` between `cancel`'s
        check and this write, and overwriting that with an interruption would
        be the app inventing an outcome. A stop that lost the race did not
        happen, and the run's own result is the true one.
        """
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None or RunStatus(run.status) not in _CANCELLABLE_STATUSES:
                # The stop lost a race with the run's own ending. Worth a line:
                # the analyst pressed Stop and the row will not say so, and
                # without this the only account of that is silence.
                _log.info(
                    "run %s: stop ignored, the run had already reached %s",
                    run_id,
                    "no row" if run is None else RunStatus(run.status).value,
                )
                return
            _log.info("run %s: stopped by request", run_id)
            run.error = _ERROR_CANCELLED
            # No `finished_at`: `interrupted` is the one state a human moves
            # out of, and a stopped run has not finished anything (`_finish`).
            await repo.set_status(run_id, RunStatus.INTERRUPTED, finished_at=None)

    # -----------------------------------------------------------------------
    # The worker body
    # -----------------------------------------------------------------------

    async def execute_run(self, run_id: RunId, reporter: ProgressReporter) -> None:
        """The worker body: resolve, call, parse, commit — per record.

        Per record, in this order: resolve the prompt through
        `PromptResolver`; call `LLMClient.extract` with the evaluation's
        temperature and seed; parse through `domain.extraction.parse_output`;
        commit one `extraction` plus its children. A **parse failure is a
        datum**: `parse_ok=False`, `parse_error` set, the raw output stored
        verbatim, and the run continues (mvp-spec.md §10.4).

        Progress is reported from committed rows, never from a counter
        (§15 F6). A process death here leaves the run `running` in the
        database, and the **next** process start relabels it `interrupted`
        (`reclaim_orphans`). Nothing in the meantime needs to notice: no read
        path writes a status, which is what makes "this row says `running`" an
        honest statement about this process rather than a guess about another.

        :raises NotFoundError: no such run.
        """
        await self._start(run_id)
        try:
            plan = await self._load_plan(run_id)
            await self._extract_all(plan, reporter)
        except Exception as exc:
            # A failure is a **recorded** outcome (mvp-spec.md §10.4): the row
            # carries why before the exception reaches the task runner. An
            # endpoint that will not answer never lands here — that leaves the
            # run `interrupted` and resumable, not `failed`.
            #
            # `Exception`, and therefore **not `asyncio.CancelledError`**,
            # which is a `BaseException`. That is load-bearing rather than
            # incidental: a run somebody stopped is not a run that failed, and
            # catching it here would both mislabel it and try to write the row
            # from inside a task that is already unwinding. `cancel` records
            # the stop from the caller's task instead.
            await self._finish(run_id, RunStatus.FAILED, error=_error_text(exc))
            raise

    async def _extract_all(self, plan: _RunPlan, reporter: ProgressReporter) -> None:
        """The record loop. Every transaction in here is opened and closed
        inside one iteration, and none of them spans the LLM call."""
        pending = await self._pending(plan.run_id, plan.corpus_id, plan.limit)
        done = await self._count_done(plan.run_id)
        total = done + len(pending)
        reporter.report(done, total, plan.model_name)
        # Ids, counts, a model tag and a bound. Nothing out of the delivery —
        # not the narrative, not `unfall_uid`, not the resolved prompt
        # (`infra/logging.py` states the rule, and a test drives a real run at
        # it). The bound is here because it is the number that decides how long
        # the next line can take to arrive.
        _log.info(
            "run %s: %d pending, %d already done, model=%s, timeout=%ds",
            plan.run_id,
            len(pending),
            done,
            plan.model_name,
            self._settings.llm_timeout_s,
        )

        consecutive_endpoint_errors = 0
        last_endpoint_error: str | None = None
        #: Records that exhausted their attempts at the endpoint, and what
        #: those attempts cost. Neither is derivable from anything committed:
        #: a record that never answered writes **no** `extraction` row, so its
        #: attempts are the one part of §10.4's "bounded, counted and visible"
        #: that had nowhere to be counted (`plan-fix-evaluation-runs.md` §1.1
        #: b). They ride out on `run.error`, which is durable and — since the
        #: "log" action was opened to any run carrying a reason — reachable.
        endpoint_failures = 0
        endpoint_attempts: int | None = 0

        for index, record_id in enumerate(pending, start=1):
            prompt_text = await self._resolve_prompt(plan, record_id)
            # **Before** the call, not only after it. On the reporting host one
            # record is over two minutes, and a line that only ever appears on
            # the way out cannot tell "waiting on the model" from "wedged".
            _log.info(
                "run %s: record %d/%d (%s) → %s",
                plan.run_id,
                index,
                len(pending),
                record_id,
                plan.model_name,
            )
            try:
                response = await self._llm_client.extract(
                    prompt_text,
                    plan.schema,
                    plan.model_name,
                    temperature=plan.temperature,
                    seed=plan.seed,
                )
            except LlmEndpointError as exc:
                # **No row.** The hole this leaves is exactly what
                # `pending_record_ids` is specified to find; a placeholder row
                # here would destroy resume (sw-design.md §15.3).
                last_endpoint_error = str(exc)
                consecutive_endpoint_errors += 1
                endpoint_failures += 1
                # `exc.status` is the `EndpointStatus` code, not prose: the
                # distinction between "nothing is listening" and "answered and
                # did not finish in time" is the whole of item 1's reasoning,
                # and it is the first thing a reader of this log wants.
                _log.warning(
                    "run %s: record %d/%d (%s) failed at the endpoint (%s) after %s attempt(s)",
                    plan.run_id,
                    index,
                    len(pending),
                    record_id,
                    exc.status.value,
                    "an unknown number of" if exc.attempts is None else exc.attempts,
                )
                # `None` the moment one failure cannot say what it cost, and
                # `None` from then on: a total that silently omits an unknown
                # is worse than no total, because it reads as complete.
                if exc.attempts is None or endpoint_attempts is None:
                    endpoint_attempts = None
                else:
                    endpoint_attempts += exc.attempts
                # `done` is the count of **committed rows for this run**, from
                # this execution or any earlier one, so this reads "has this
                # configuration ever worked" rather than "is this the first
                # record I tried".
                if consecutive_endpoint_errors >= _endpoint_error_budget(done):
                    break
                continue
            consecutive_endpoint_errors = 0
            await self._commit_record(plan, record_id, response)
            done = await self._count_done(plan.run_id)
            reporter.report(done, total, plan.model_name)
            # `parse_ok` is a **datum**, not an error (§15.3), so this is INFO
            # whichever way it went. What the model actually said is the
            # `extraction` row's business and never this one's.
            _log.info(
                "run %s: record %d/%d answered in %s ms, parse_ok=%s, retries=%d (%d/%d done)",
                plan.run_id,
                index,
                len(pending),
                response.latency_ms,
                response.parse_ok,
                response.retry_count,
                done,
                total,
            )

        remaining = await self._pending(plan.run_id, plan.corpus_id, plan.limit)
        if remaining:
            # Not `failed`: the work that landed is good and the rest is
            # resumable, which is what `interrupted` means (§15 F8). The
            # missing records are named by count, never silently dropped
            # (Do-NOT #6) — `pending_record_ids` re-derives exactly which.
            reason = last_endpoint_error or "the endpoint stopped answering"
            cost = _endpoint_cost(endpoint_failures, endpoint_attempts)
            await self._finish(
                plan.run_id,
                RunStatus.INTERRUPTED,
                error=(
                    f"interrupted with {len(remaining)} record(s) not extracted{cost}: {reason}"
                ),
            )
        else:
            await self._finish(plan.run_id, RunStatus.DONE, error=None)

    async def _resolve_prompt(self, plan: _RunPlan, record_id: RecordId) -> str:
        """The resolved prompt for one record, in a transaction of its own
        that is **closed before the model is called**."""
        async with session_scope(self._session_factory) as session:
            resolved = await self._prompt_resolver.resolve(session, plan.evaluation_id, record_id)
        return resolved.text

    async def _commit_record(
        self, plan: _RunPlan, record_id: RecordId, response: LlmOutput[BaseModel]
    ) -> None:
        """One `extraction` row plus its children, in **one** transaction.

        The parse happens before the session is opened: `parse_output` is pure
        and there is no reason for a transaction to be open while it runs.
        """
        row = self._build_row(plan, record_id, response)
        async with session_scope(self._session_factory) as session:
            await ExtractionRepository(session).add(row)

    def _build_row(
        self, plan: _RunPlan, record_id: RecordId, response: LlmOutput[BaseModel]
    ) -> Extraction:
        """The `extraction` row and its children, parsed but unwritten.

        The adapter's verdict wins when it has one: an `Extraction` arriving
        with `parse_ok=False` was already judged unreadable at the seam, and
        re-parsing it here to disagree would make two authorities out of one.
        Everything else goes through `domain.extraction.parse_output`, which
        never raises and never repairs.
        """
        parsed: ParsedExtraction | ParseFailure
        if response.parse_ok:
            parsed = parse_output(
                response.raw_output_text,
                plan.features,
                enum_codelists=plan.enum_codelists,
            )
        else:
            parsed = ParseFailure(reason=response.parse_error or _REASON_ADAPTER_PARSE_FAILED)

        row = Extraction(
            id=ExtractionId(self._ids.new_id()),
            run_id=plan.run_id,
            record_id=record_id,
            # Verbatim, whatever the verdict: the raw text is the evidence
            # (mvp-spec.md §10.4).
            raw_output_text=response.raw_output_text,
            parse_ok=isinstance(parsed, ParsedExtraction),
            parse_error=None if isinstance(parsed, ParsedExtraction) else parsed.reason,
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            retry_count=response.retry_count,
        )
        if isinstance(parsed, ParsedExtraction):
            row.values = [
                ExtractionValue(
                    feature_id=plan.feature_ids[value.feature_key],
                    value_raw=value.value_raw,
                    value_normalised=value.value_normalised,
                    present_flag=value.present_flag,
                    evidence_span=value.evidence_span,
                )
                for value in parsed.values
                # An `UNKNOWN_FEATURE` answer has no `feature` row to hang
                # off. It is already recorded as a parse issue on the response
                # that carries it, and inventing a feature id for it would be
                # a repair (Do-NOT #6).
                if value.feature_key in plan.feature_ids
            ]
            row.entities = [
                ExtractionEntity(
                    id=self._ids.new_id(),
                    entity_kind=entity.kind,
                    entity_ref=entity.ref,
                    attributes_json=_dump_attributes(entity.attributes),
                )
                for entity in parsed.entities
            ]
        return row

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def _start(self, run_id: RunId) -> None:
        """`queued -> running`, with the host half of the provenance.

        **Written at run start, not at completion** (§15.4): a run that dies
        mid-corpus is still a reproducible run. Only blank fields are filled —
        `EvaluationService.launch` writes the pinned inputs (model + digest,
        template version + fingerprint, temperature, seed) when it creates the
        row, and a resume on another host must not rewrite the history of the
        run it is continuing.

        :raises NotFoundError: no such run.
        """
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            if not run.host_platform:
                run.host_platform = platform.platform()
            if not run.llm_endpoint:
                run.llm_endpoint = self._settings.llm_base_url
            if run.llm_reasoning_effort is None:
                run.llm_reasoning_effort = self._settings.llm_reasoning_effort
            if run.gpu_name is None:
                gpu = self._gpu_probe.describe()
                # `None` stays `None`: no NVIDIA GPU is an honest answer, not
                # a missing one (sw-design.md §15.6).
                run.gpu_name = gpu.name if gpu is not None else None
            await repo.set_status(run_id, RunStatus.RUNNING, started_at=self._clock.now())

    async def _finish(self, run_id: RunId, status: RunStatus, *, error: str | None) -> None:
        """The run's last status write. `finished_at` is stamped only for a
        **terminal** status — `interrupted` is the one state a human moves out
        of, so a run sitting in it has not finished anything."""
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None:  # pragma: no cover - deleted mid-run
                return
            # Assigned directly rather than through `set_status(error=…)`,
            # which by design ignores a `None`: a resume that completes the run
            # must clear the interruption it is completing.
            run.error = error
            terminal = status in (RunStatus.DONE, RunStatus.FAILED)
            await repo.set_status(
                run_id, status, finished_at=self._clock.now() if terminal else None
            )
        # `error` is this module's own sentence about the run — a count of
        # records and an endpoint status — and never the model's words, so it
        # is safe to repeat here. It is also the one thing worth having in the
        # terminal: the same text the "log" action shows, at the moment it was
        # decided rather than whenever somebody thinks to look.
        level = logging.INFO if status is RunStatus.DONE else logging.WARNING
        _log.log(level, "run %s: %s%s", run_id, status.value, f" — {error}" if error else "")

    async def reclaim_orphans(self) -> int:
        """Relabel every run left `running` by a process that died under it.

        Called **once, from the composition root's startup**, before anything
        in this process can submit work — and from nowhere else, which
        `tests/test_reclaim_is_called_once.py` is the gate on. That precondition
        is not a detail, it is the whole design: at startup this process is
        executing nothing, so a row the database still calls `running` is
        stale **unconditionally**. There is no set to consult, no claim to hold
        and no window to get wrong.

        `RunRepository.list_running` has said so since it was written — *"on
        the next startup it is still `running` in the database though nothing
        is executing it"* — and had no caller. What existed instead reclaimed
        on every read path, which is where the two races came from: the
        Evaluation view polls those paths twice a tick for the length of a run,
        so every instant in which the row said `running` and the in-memory
        claim had not caught up was an instant a poll could land in and write
        `_ERROR_INTERRUPTED_BY_RESTART` — a specific, false claim about a
        process that was fine. Asking once, when the answer cannot be wrong,
        removes the question rather than timing it better.

        Two things it is deliberately not:

        - **Not a restart.** Relabelled only (§15 F8). A run that restarted
          itself on every app start would burn GPU hours on work the user may
          have abandoned; Resume is an explicit human act.
        - **Not aware of other processes.** Two apps sharing one
          `RA2_DATA_DIR` would have the second declare the first's live runs
          dead. That was true of the read-path version too, continuously
          rather than once, so this is strictly the safer of the two — but it
          is why `just dev` binds a fixed port and `dev-agent` mints its own
          data directory.

        :returns: how many runs were relabelled, so the caller can say so.
        """
        async with session_scope(self._session_factory) as session:
            stale = await RunRepository(session).list_running()
            for run in stale:
                run.status = RunStatus.INTERRUPTED
                run.error = _ERROR_INTERRUPTED_BY_RESTART
            await session.flush()
        if stale:
            # The loudest thing this service says, because it is a verdict on
            # processes that are not here to answer. A timestamp on it is what
            # lets a reader set it beside whatever killed them — uvicorn's own
            # "Reloading" line, for the one this was found from.
            _log.warning(
                "%d run(s) were left running by a process that died — marked interrupted",
                len(stale),
            )
        return len(stale)

    # -----------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------

    async def progress(self, run_id: RunId) -> RunProgressView:
        """One progress card's content, derived from committed rows.

        :raises NotFoundError: no such run.
        """
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            # No reclaim. **A read never writes a status** — restart
            # detection happens once, at process start
            # (`reclaim_orphans`), where the answer cannot be wrong.
            evaluation = await EvaluationRepository(session).get(EvaluationId(run.evaluation_id))
            done = await repo.count_done(run_id)
            pending = (
                0
                if evaluation is None
                else len(
                    await ExtractionRepository(session).pending_record_ids(
                        run_id,
                        CorpusId(evaluation.corpus_id),
                        limit=self._record_limit(evaluation),
                    )
                )
            )
            elapsed_ms = self._elapsed_ms(run)
            return RunProgressView(
                run_id=run_id,
                model_tag=run.model_name,
                status=RunStatus(run.status),
                done=done,
                total=done + pending,
                parse_failures=await repo.count_parse_failures(run_id),
                retries=await repo.sum_retries(run_id),
                median_latency_ms=await _median_latency_ms(session, run_id),
                prompt_tokens=await _sum_prompt_tokens(session, run_id),
                elapsed_ms=elapsed_ms,
                eta_ms=_eta_ms(elapsed_ms, done=done, remaining=pending),
            )

    async def list_runs(
        self,
        evaluation_id: EvaluationId,
        *,
        page: int = 1,
        page_size: int = 10,
        sort_key: str = "started_at",
        sort_dir: SortDir = SortDir.DESC,
    ) -> Page[RunView]:
        """The "Runs in this evaluation" table — paginated at 10, as drawn.

        Sort and page are **service-call parameters**, not view-local state
        (sw-design.md §8.1.4).
        """
        key = sort_key if sort_key in _SORT_KEYS else "started_at"
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            runs = await repo.list_by_evaluation(evaluation_id)
            evaluation = await EvaluationRepository(session).get(evaluation_id)
            is_dev = _is_dev(evaluation)
            ordinals = run_ordinals(runs)
            views = [
                _run_view(
                    run,
                    records_done=await repo.count_done(RunId(run.id)),
                    is_dev=is_dev,
                    ordinal=ordinals[run.id],
                )
                for run in runs
            ]

        # Sorted here rather than in SQL, for `list_corpora`'s reason: the
        # repository offers no paged query and an evaluation holds a handful
        # of runs. The parameters are still the service call's (§8.1.4).
        _sort_runs(views, key=key, sort_dir=sort_dir)
        start = max(page - 1, 0) * page_size
        return Page(
            items=tuple(views[start : start + page_size]),
            total=len(views),
            page=page,
            page_size=page_size,
            sort_key=key,
            sort_dir=sort_dir,
        )

    async def get(self, run_id: RunId) -> RunView:
        """:raises NotFoundError: no such run."""
        async with session_scope(self._session_factory) as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            evaluation = await EvaluationRepository(session).get(EvaluationId(run.evaluation_id))
            # The siblings are read for one number, because the ordinal is a
            # property of the set and there is no honest way to know a run's
            # place from the run alone. An evaluation holds a handful of runs.
            siblings = await repo.list_by_evaluation(EvaluationId(run.evaluation_id))
            return _run_view(
                run,
                records_done=await repo.count_done(run_id),
                is_dev=_is_dev(evaluation),
                ordinal=run_ordinals(siblings)[run.id],
            )

    # -----------------------------------------------------------------------
    # Shared reads
    # -----------------------------------------------------------------------

    async def _load_plan(self, run_id: RunId) -> _RunPlan:
        """Read the run, its evaluation and the launch snapshot — once.

        :raises NotFoundError: the run or its evaluation is gone.
        :raises FeatureValidationError: the evaluation has no
            `evaluation_feature` snapshot. That snapshot is written by the
            launch transaction and is the authority on what the model is asked
            (§15.2); a run without one cannot be executed, and guessing from
            the draft's current feature set would ask a different question
            than the one the run's fingerprints claim.
        """
        async with self._session_factory() as session:
            run = await RunRepository(session).get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            evaluation_id = EvaluationId(run.evaluation_id)
            evaluation = await EvaluationRepository(session).get(evaluation_id)
            if evaluation is None:  # pragma: no cover - FK CASCADE makes this unreachable
                raise NotFoundError("evaluation", evaluation_id)

            snapshot = await _snapshot_features(session, evaluation_id)
            if not snapshot:
                raise FeatureValidationError(
                    [f"evaluation {evaluation_id} has no feature snapshot; launch writes it"]
                )
            entries = tuple(_feature_block_entry(feature) for feature, _ in snapshot)
            return _RunPlan(
                run_id=run_id,
                evaluation_id=evaluation_id,
                corpus_id=CorpusId(evaluation.corpus_id),
                model_name=run.model_name,
                # The **run**'s own copies, not the evaluation's: they are the
                # provenance this run is reproducible against (§19.8).
                temperature=run.temperature,
                seed=run.seed,
                limit=self._record_limit(evaluation),
                features=entries,
                feature_ids={feature.key: FeatureId(feature.id) for feature, _ in snapshot},
                enum_codelists={
                    feature.key: codes
                    for feature, codelist in snapshot
                    if (codes := _codes_of(codelist)) is not None
                },
                schema=build_output_schema(entries),
            )

    def _record_limit(self, evaluation: Evaluation) -> int | None:
        """The dev cap, or `None` for the whole corpus.

        A `DEV` selection is the **first `RA2_DEV_RECORD_MAX` records by id** —
        deterministic, because "a re-run is a check, not a new sample" is false
        the moment the selection is random (§15 F9).
        """
        if EvaluationSize(evaluation.size) is EvaluationSize.DEV:
            return self._settings.dev_record_max
        return None

    async def _pending(
        self, run_id: RunId, corpus_id: CorpusId, limit: int | None
    ) -> list[RecordId]:
        async with self._session_factory() as session:
            return await ExtractionRepository(session).pending_record_ids(
                run_id, corpus_id, limit=limit
            )

    async def _count_done(self, run_id: RunId) -> int:
        """`COUNT(extraction WHERE run_id = …)`, in a session of its own —
        progress is **derived**, never counted (§15 F6)."""
        async with self._session_factory() as session:
            return await RunRepository(session).count_done(run_id)

    async def _counts(self, run_id: RunId) -> tuple[int, int]:
        """`(done, pending)` for one run, both derived.

        :raises NotFoundError: no such run.
        """
        async with self._session_factory() as session:
            run = await RunRepository(session).get(run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            evaluation = await EvaluationRepository(session).get(EvaluationId(run.evaluation_id))
            if evaluation is None:  # pragma: no cover - FK CASCADE makes this unreachable
                raise NotFoundError("evaluation", run.evaluation_id)
            done = await RunRepository(session).count_done(run_id)
            pending = await ExtractionRepository(session).pending_record_ids(
                run_id, CorpusId(evaluation.corpus_id), limit=self._record_limit(evaluation)
            )
            return done, len(pending)

    def _elapsed_ms(self, run: Run) -> int | None:
        started = run.started_at
        if started is None:
            return None
        end = run.finished_at or self._clock.now()
        return max(int((end - started).total_seconds() * 1000), 0)


# ===========================================================================
# Pure helpers
# ===========================================================================


def _error_text(exc: BaseException) -> str:
    """What `run.error` records — the runs table's muted "log" action.

    `FeatureValidationError` keeps its detail in `validation_errors` and
    stringifies to a count, which is the right shape for a 422 body and the
    wrong one for a line someone has to act on.
    """
    if isinstance(exc, FeatureValidationError):
        return f"{type(exc).__name__}: {'; '.join(exc.validation_errors)}"
    return f"{type(exc).__name__}: {exc}"


def _dump_attributes(attributes: Mapping[str, str]) -> str:
    return json.dumps(dict(attributes), **_JSON_KWARGS)  # type: ignore[arg-type]


def _is_dev(evaluation: Evaluation | None) -> bool:
    """Whether every view of this run must carry "smoke test, not a result".

    Two ways in, one meaning: a `DEV`-sized **selection** (step 6), and a
    corpus small enough that `EvaluationService.launch` stamped
    `evaluation.is_dev` from `RA2_EVAL_RECORD_MIN` (mvp-spec.md §9).
    """
    if evaluation is None:
        return False
    return evaluation.is_dev or EvaluationSize(evaluation.size) is EvaluationSize.DEV


def _endpoint_cost(failures: int, attempts: int | None) -> str:
    """What the records that never answered cost, as a clause or nothing.

    Separate from the records *not extracted*, which is the larger number: the
    worker stops after `_endpoint_error_budget` failures, so most of what is
    missing was never attempted at all. Conflating "12 records have no
    extraction" with "12 records were tried and refused" would overstate the
    evidence by an order of magnitude.

    Empty when there were no endpoint failures, so a run interrupted for some
    other reason does not grow a clause about a thing that did not happen.
    """
    if failures <= 0:
        return ""
    records = "record" if failures == 1 else "records"
    if attempts is None:
        return f"; {failures} {records} failed at the endpoint"
    calls = "attempt" if attempts == 1 else "attempts"
    return f"; {failures} {records} failed at the endpoint after {attempts} {calls}"


def _endpoint_error_budget(done: int) -> int:
    """How many consecutive endpoint failures this run tolerates.

    The two constants have the reasoning; this is the one line that chooses
    between them, kept separate so the choice is testable without driving a
    whole run at it.
    """
    if done > 0:
        return _MAX_CONSECUTIVE_ENDPOINT_ERRORS
    return _MAX_ENDPOINT_ERRORS_BEFORE_FIRST_ROW


def run_ordinals(runs: Sequence[Run]) -> dict[str, int]:
    """`run.id -> its 1-based place in the evaluation`, by **creation order**.

    Sorted by id here rather than taken in the caller's own order, which is
    `started_at DESC` (`RunRepository.list_by_evaluation`) — the *display*
    order, where a run's number would change as its siblings start, and change
    again under every other sort the table offers. A number that moves is not
    an identifier.

    Id order is creation order because the ids are uuid7, which is time-
    ordered by construction. `launch_runs` already sorts runs by id on that
    reasoning, and `mismatch_service._run_label` counts positions in a query
    that is explicitly `ORDER BY run.id`. This is that same count, stated once
    so the runs table and the discard dialog cannot disagree about which run
    is "run 2".
    """
    return {run.id: i for i, run in enumerate(sorted(runs, key=lambda r: r.id), start=1)}


def _run_view(run: Run, *, records_done: int, is_dev: bool, ordinal: int) -> RunView:
    status = RunStatus(run.status)
    return RunView(
        run_id=RunId(run.id),
        ordinal=ordinal,
        evaluation_id=EvaluationId(run.evaluation_id),
        model_tag=run.model_name,
        model_digest=run.model_digest,
        records_done=records_done,
        started_at=run.started_at,
        status=status,
        is_dev=is_dev,
        # Whatever the row carries, whatever the status. This used to be
        # `run.error if status is RunStatus.FAILED else None`, on the reading
        # that "log" was the failure's action — which meant an `interrupted`
        # run's reason was written by `_finish` and then dropped here, one
        # layer before the only screen that could have shown it. An endpoint
        # that timed out and one that was never there leave the same row and
        # the same Resume button, and the sentence telling them apart existed
        # the whole time (plan-fix-evaluation-runs.md §1.1 e).
        error=run.error,
    )


def _sort_runs(views: list[RunView], *, key: str, sort_dir: SortDir) -> None:
    """Sort in place, `NULL` timestamps last in **both** directions.

    A `queued` run has no `started_at`, and SQLite's own `DESC` ordering puts
    those at the bottom (`RunRepository.list_by_evaluation`). Ascending has to
    agree with it: a not-yet-started run is not the oldest run.
    """
    descending = sort_dir is SortDir.DESC
    if key == "started_at":
        views.sort(
            key=lambda v: (
                (v.started_at is not None) if descending else (v.started_at is None),
                v.started_at or datetime.min.replace(tzinfo=UTC),
                v.run_id,
            ),
            reverse=descending,
        )
        return
    views.sort(key=lambda v: (str(getattr(v, key)), v.run_id), reverse=descending)


def _eta_ms(elapsed_ms: int | None, *, done: int, remaining: int) -> int | None:
    """Linear extrapolation from what has actually been committed.

    `None` until there is one committed record to extrapolate from — an ETA
    computed from zero records is a guess wearing a number's clothes.
    """
    if elapsed_ms is None or done <= 0 or remaining <= 0:
        return None
    return int(elapsed_ms / done * remaining)


async def _snapshot_features(
    session: AsyncSession, evaluation_id: EvaluationId
) -> list[tuple[Feature, str | None]]:
    """The evaluation's launch snapshot, joined to the features it names.

    Ordered by `feature.ordinal` so the output schema's key order is the
    feature set's own order and is identical across two runs of the same
    evaluation (§15.3). `evaluation_feature` carries no ordinal of its own.
    """
    stmt = (
        select(Feature, EvaluationFeature.enum_codelist_json)
        .join(EvaluationFeature, EvaluationFeature.feature_id == Feature.id)
        .where(EvaluationFeature.evaluation_id == evaluation_id)
        .order_by(Feature.ordinal, Feature.key)
    )
    rows = await session.execute(stmt)
    return [(feature, codelist) for feature, codelist in rows.all()]


def _feature_block_entry(feature: Feature) -> FeatureBlockEntry:
    """One feature, reduced to what the schema and the parser may see.

    `enum_codelist` stays `None`: it is the *prompt*'s rendering of the
    snapshot and belongs to `PromptResolver`, the one thing in this phase that
    renders it. `parse_output` takes the codes it validates against as a
    separate argument, and that is the path this module uses.
    """
    return FeatureBlockEntry(
        key=feature.key,
        kind=Kind(feature.kind),
        grain=Grain(feature.grain),
        value_type=ValueType(feature.value_type),
        description=feature.description,
        matching_rule=matching_rule_from_json(feature.matching_rule),
        enum_codelist=None,
    )


def _codes_of(codelist_json: str | None) -> frozenset[str] | None:
    """The snapshot's codes, for `parse_output`'s `enum_codelists`.

    The snapshot is `{code: label}` — the same shape
    `FingerprintInput.enum_codelist_json` hashes. Anything else yields `None`,
    which means "no snapshot to check against": an `ENUM_CODE_NOT_IN_CODELIST`
    issue raised against a codelist this module had guessed at would be a
    finding about its own parsing, not about the model's answer.
    """
    if not codelist_json:
        return None
    try:
        data = json.loads(codelist_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return frozenset(str(code) for code in data)


async def _median_latency_ms(session: AsyncSession, run_id: RunId) -> int | None:
    """The metrics line's median latency, over committed rows.

    Two indexed queries rather than one `list_for_run()`: the progress card is
    polled on a `ui.timer` and loading every extraction with its children once
    a second to take a median would make the cheap number the expensive one.
    SQLite has no `median()`, so this is `ORDER BY … LIMIT 1 OFFSET n/2` — the
    lower median for an even count, which is a real observed latency rather
    than an average of two.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(Extraction)
        .where(Extraction.run_id == run_id, Extraction.latency_ms.is_not(None))
    )
    if not count:
        return None
    value = await session.scalar(
        select(Extraction.latency_ms)
        .where(Extraction.run_id == run_id, Extraction.latency_ms.is_not(None))
        .order_by(Extraction.latency_ms)
        .limit(1)
        .offset((int(count) - 1) // 2)
    )
    return None if value is None else int(value)


async def _sum_prompt_tokens(session: AsyncSession, run_id: RunId) -> int:
    """The **real** counts from the endpoint, summed — never the preview's
    estimate (`domain.prompt.estimate_tokens`)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Extraction.prompt_tokens), 0)).where(
            Extraction.run_id == run_id
        )
    )
    return int(total or 0)
