# STUB — bodies owned by H3 (feat/p3-persistence). Not frozen.
"""Run persistence: create, status transitions, progress counts
(mvp-spec.md §5/§9, sw-design.md §15.2/§15.4).

**There is deliberately no `records_done` column** (§15 F6). `count_done()`
below is `COUNT(extraction WHERE run_id = …)` over `ix_extraction_run_id` —
the run's progress is derived from committed `extraction` rows every time it
is asked for, never read from a counter a restart could disagree with. This
is why the method lives here rather than a cached field on `Run`: do not add
one.

`Run` rows are otherwise mutated in place across their lifecycle
(`queued -> running -> done|failed|interrupted`) — a status transition is not
a new row, unlike `extraction`.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import EvaluationId, RunId
from ra2.persistence.models import Extraction, Mismatch, Run, Score

__all__ = ["RunRepository"]


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: Run) -> None:
        self._session.add(run)
        await self._session.flush()

    async def get(self, run_id: RunId) -> Run | None:
        stmt = select(Run).where(Run.id == run_id)
        result: Run | None = await self._session.scalar(stmt)
        return result

    async def list_by_evaluation(self, evaluation_id: EvaluationId) -> list[Run]:
        """The "Runs in this evaluation" table's rows, most recently started
        first. A `queued` run has no `started_at` yet; SQLite sorts `NULL`
        last in a `DESC` ordering, which puts not-yet-started runs at the
        bottom — the design's own ordering."""
        stmt = select(Run).where(Run.evaluation_id == evaluation_id).order_by(Run.started_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_running(self) -> list[Run]:
        """Every run still marked `running`.

        Reads as an odd thing to persist a query for, until a process dies
        mid-run: nothing updates that row's status on the way down, so on the
        next startup it is still `running` in the database though nothing is
        executing it. This is how a caller finds those and moves them to
        `interrupted` (§15.4) — never automatically resumed, only relabelled
        honestly (§15 F8).
        """
        stmt = select(Run).where(Run.status == RunStatus.RUNNING)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def set_status(
        self,
        run_id: RunId,
        status: RunStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Moves a run to `status`, updating only the timestamps/error the
        caller passes — `started_at` on `queued -> running`, `finished_at`
        (and `error` on failure) on the way to a terminal status. No-op if
        the id is unknown (the `FeatureRepository` convention).
        """
        run = await self.get(run_id)
        if run is None:
            return
        run.status = status
        if started_at is not None:
            run.started_at = started_at
        if finished_at is not None:
            run.finished_at = finished_at
        if error is not None:
            run.error = error
        await self._session.flush()

    async def count_done(self, run_id: RunId) -> int:
        """`COUNT(extraction WHERE run_id = …)` — the run's progress,
        **derived, never counted** (§15 F6). Every `RunProgressView.done` and
        `RunView.records_done` traces back to this query, not to a column."""
        count = await self._session.scalar(
            select(func.count()).select_from(Extraction).where(Extraction.run_id == run_id)
        )
        return int(count or 0)

    async def count_parse_failures(self, run_id: RunId) -> int:
        """How many committed extractions for this run have `parse_ok=False`
        — the progress card's "parse failures" metric, derived the same way
        as `count_done` (§15.3: a parse failure is a datum, not an
        exception, and it must be countable without a second column)."""
        count = await self._session.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.run_id == run_id, Extraction.parse_ok.is_(False))
        )
        return int(count or 0)

    async def sum_retries(self, run_id: RunId) -> int:
        """Total retries spent so far on this run's committed extractions —
        the metrics line's "retries N (bounded, counted)" (mvp-spec.md
        §10.4), derived from `extraction.retry_count` rather than a running
        counter on `run`."""
        total = await self._session.scalar(
            select(func.coalesce(func.sum(Extraction.retry_count), 0)).where(
                Extraction.run_id == run_id
            )
        )
        return int(total or 0)

    # --- discard (sw-design.md §18) ----------------------------------------

    async def count_scores(self, run_id: RunId) -> int:
        """How many `score` rows this run would take with it."""
        count = await self._session.scalar(
            select(func.count()).select_from(Score).where(Score.run_id == run_id)
        )
        return int(count or 0)

    async def count_mismatches(self, run_id: RunId) -> tuple[int, int]:
        """`(all, tagged)` in one query.

        The second number is **G2** (§18.2): `analyst_tag` is the one
        human-authored column in the pipeline, and a discard that would
        destroy some announces how many before it does.
        """
        row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count(Mismatch.analyst_tag),
                ).where(Mismatch.run_id == run_id)
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    async def delete(self, run: Run) -> None:
        """Remove the run. `extraction`, `extraction_value`,
        `extraction_entity`, `score` and `mismatch` go with it **by the
        schema's own `ondelete="CASCADE"`**, not by anything written here
        (§18.1) — which is why `foreign_keys=ON` being a connect-time PRAGMA
        (§4.4) is load-bearing rather than tidy.
        """
        await self._session.delete(run)
        await self._session.flush()
