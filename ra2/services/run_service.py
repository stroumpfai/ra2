# STUB — bodies owned by I3 (feat/p3-run-service). Not frozen.
"""The run worker (sw-design.md §15.4, mvp-spec.md §9/§10, N6).

The `TaskRunner` seam (SD7) with a persistent tail — one submitted job per
`run`, `ProgressReporter` for the UI, and the `run` / `extraction` tables for
everything that has to survive the process. `GET /api/v1/tasks/{id}` (§9) is
unchanged; the UI polls it with `ui.timer` exactly as Import does. No
streaming, no websocket push.

Four properties this module exists to guarantee:

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

import json
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
from ra2.services.errors import FeatureValidationError, NotFoundError
from ra2.services.feature_service import matching_rule_from_json
from ra2.services.protocols import PromptResolver
from ra2.services.readmodels import Page, RunProgressView, RunView, SortDir

__all__ = ["RunService"]

#: `sort_key` -> the `RunView` attribute it sorts on. An unknown key falls
#: back to `started_at`, the runs table's own default (sw-design.md §8.1.4).
_SORT_KEYS: Final[frozenset[str]] = frozenset({"started_at", "model_tag", "status", "records_done"})

#: How many records in a row may fail at the endpoint before the worker stops
#: asking. One failure is a **record**'s problem and leaves a hole the resume
#: query finds; three in a row is the **endpoint**'s problem, and grinding a
#: 5 000-record corpus through `RA2_LLM_TIMEOUT_S` × `RA2_LLM_MAX_RETRIES`
#: apiece to discover that would be neither honest nor bounded. The run is
#: left `interrupted` either way, which is the state Resume acts on (§15 F8).
#: Deliberately not a setting: it is a property of "the endpoint is down", not
#: a knob an analyst has any basis to turn.
_MAX_CONSECUTIVE_ENDPOINT_ERRORS: Final = 3

#: `extraction.parse_error` when the *adapter* already judged the response
#: unreadable (`Extraction.parse_ok is False`) but named no reason. A stable
#: identifier, like `domain.extraction`'s own reasons — asserted on, never
#: rendered as prose.
_REASON_ADAPTER_PARSE_FAILED: Final = "adapter_parse_failed"

#: `run.error` on a run this process found still marked `running` although
#: nothing is executing it — the process died under it (§15.4). Relabelling is
#: all that happens: **nothing auto-restarts** (§15 F8).
_ERROR_INTERRUPTED_BY_RESTART: Final = "interrupted: the process died while this run was executing"

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
        #: The runs **this process** is executing right now. A `running` row
        #: that is not in here belongs to a process that died under it, which
        #: is the whole of how a restart is detected (see `_reclaim`).
        self._active: set[RunId] = set()

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
            await self.execute_run(run_id, _OffsetReporter(reporter, base=base, total=grand_total))
            # Advanced by what actually committed, not by the scope size: a
            # run that ends `interrupted` leaves the job's bar short of 100 %,
            # which is the honest picture of it.
            base += await self._count_done(run_id)

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
        (§15 F6). A process death here leaves the run `interrupted`.

        :raises NotFoundError: no such run.
        """
        await self._start(run_id)
        self._active.add(run_id)
        try:
            plan = await self._load_plan(run_id)
            await self._extract_all(plan, reporter)
        except Exception as exc:
            # A failure is a **recorded** outcome (mvp-spec.md §10.4): the row
            # carries why before the exception reaches the task runner. An
            # endpoint that will not answer never lands here — that leaves the
            # run `interrupted` and resumable, not `failed`.
            await self._finish(run_id, RunStatus.FAILED, error=_error_text(exc))
            raise
        finally:
            self._active.discard(run_id)

    async def _extract_all(self, plan: _RunPlan, reporter: ProgressReporter) -> None:
        """The record loop. Every transaction in here is opened and closed
        inside one iteration, and none of them spans the LLM call."""
        pending = await self._pending(plan.run_id, plan.corpus_id, plan.limit)
        done = await self._count_done(plan.run_id)
        total = done + len(pending)
        reporter.report(done, total, plan.model_name)

        consecutive_endpoint_errors = 0
        last_endpoint_error: str | None = None

        for record_id in pending:
            prompt_text = await self._resolve_prompt(plan, record_id)
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
                if consecutive_endpoint_errors >= _MAX_CONSECUTIVE_ENDPOINT_ERRORS:
                    break
                continue
            consecutive_endpoint_errors = 0
            await self._commit_record(plan, record_id, response)
            done = await self._count_done(plan.run_id)
            reporter.report(done, total, plan.model_name)

        remaining = await self._pending(plan.run_id, plan.corpus_id, plan.limit)
        if remaining:
            # Not `failed`: the work that landed is good and the rest is
            # resumable, which is what `interrupted` means (§15 F8). The
            # missing records are named by count, never silently dropped
            # (Do-NOT #6) — `pending_record_ids` re-derives exactly which.
            reason = last_endpoint_error or "the endpoint stopped answering"
            await self._finish(
                plan.run_id,
                RunStatus.INTERRUPTED,
                error=f"interrupted with {len(remaining)} record(s) not extracted: {reason}",
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

    async def _reclaim(self, session: AsyncSession, runs: Sequence[Run]) -> None:
        """Relabel runs left `running` by a process that died under them.

        `RunRepository.list_running` exists for exactly this (§15.4) and the
        read paths are where it is cheap to ask: the Evaluation view is what
        shows a run's state, and a run this process is not executing but the
        database still calls `running` is a run whose process is gone.

        **Relabelled, never restarted** (§15 F8). `self._active` is what tells
        the two apart: a run being executed right now, in this process, is in
        it — a run from a previous process cannot be.
        """
        stale = [
            run
            for run in runs
            if RunStatus(run.status) is RunStatus.RUNNING and RunId(run.id) not in self._active
        ]
        if not stale:
            return
        for run in stale:
            run.status = RunStatus.INTERRUPTED
            run.error = _ERROR_INTERRUPTED_BY_RESTART
        await session.flush()

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
            await self._reclaim(session, [run])

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
            await self._reclaim(session, runs)
            evaluation = await EvaluationRepository(session).get(evaluation_id)
            is_dev = _is_dev(evaluation)
            views = [
                _run_view(run, records_done=await repo.count_done(RunId(run.id)), is_dev=is_dev)
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
            await self._reclaim(session, [run])
            evaluation = await EvaluationRepository(session).get(EvaluationId(run.evaluation_id))
            return _run_view(
                run,
                records_done=await repo.count_done(run_id),
                is_dev=_is_dev(evaluation),
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
        started = _as_utc(run.started_at)
        if started is None:
            return None
        end = _as_utc(run.finished_at) or self._clock.now()
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


def _run_view(run: Run, *, records_done: int, is_dev: bool) -> RunView:
    status = RunStatus(run.status)
    return RunView(
        run_id=RunId(run.id),
        evaluation_id=EvaluationId(run.evaluation_id),
        model_tag=run.model_name,
        model_digest=run.model_digest,
        records_done=records_done,
        started_at=run.started_at,
        status=status,
        is_dev=is_dev,
        # "`None` unless `FAILED`" (readmodels.py). An interrupted run's own
        # reason is on the row either way; the table's "log" action is the
        # failure's.
        error=run.error if status is RunStatus.FAILED else None,
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
                _as_utc(v.started_at) or datetime.min.replace(tzinfo=UTC),
                v.run_id,
            ),
            reverse=descending,
        )
        return
    views.sort(key=lambda v: (str(getattr(v, key)), v.run_id), reverse=descending)


def _as_utc(value: datetime | None) -> datetime | None:
    """A stored timestamp as an aware UTC one.

    SQLite has no timezone type: a `DateTime(timezone=True)` column round trips
    as naive on some drivers and aware on others, and an elapsed-time
    subtraction across the two raises. Naive is read as UTC because UTC is what
    `Clock.now()` writes.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
