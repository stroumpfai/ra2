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
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId, RunId, TaskId
from ra2.domain.llm import LLMClient
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuProbe
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import ProgressReporter, TaskRunner
from ra2.services.protocols import PromptResolver
from ra2.services.readmodels import Page, RunProgressView, RunView, SortDir

__all__ = ["RunService"]


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

    async def launch_runs(self, evaluation_id: EvaluationId) -> TaskId:
        """Submit the `queued` runs `EvaluationService.launch` created.

        One `TaskRunner` job for the evaluation, executing its runs
        **serially** — `RA2_RUN_CONCURRENCY` is 1 and nothing in this phase
        raises it. Returns the task id the UI polls.

        :raises NotFoundError: no such evaluation.
        """
        raise NotImplementedError

    async def resume(self, run_id: RunId) -> TaskId:
        """Pick an `interrupted` run back up. **Explicit, never automatic.**

        Resume is "the record ids in this run's scope with no `extraction`
        row" — `UNIQUE (run_id, record_id)` *is* the resume key. The set can
        have **holes in the middle**, not just a missing tail: a record whose
        retries were exhausted leaves one.

        N6 asks for restart-*safe* and resumable, which this is; it does not
        ask for automatic, and a run that restarts itself whenever the app
        starts burns GPU hours on work the user may have abandoned (§15 F8).

        :raises NotFoundError: no such run.
        """
        raise NotImplementedError

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
        """
        raise NotImplementedError

    async def progress(self, run_id: RunId) -> RunProgressView:
        """One progress card's content, derived from committed rows.

        :raises NotFoundError: no such run.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    async def get(self, run_id: RunId) -> RunView:
        """:raises NotFoundError: no such run."""
        raise NotImplementedError
