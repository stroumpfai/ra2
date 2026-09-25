"""What this host measured about a model, taken and kept (sw-design.md SD40).

`just qualify-model` drives two apps. A **throwaway** one, over the synthetic
seed in a temporary data dir, runs ordinary evaluations. This service reads
their figures back there (`quality`, `answer_fingerprints`, `pass_wall_ms`).
The **target** app, the configured `RA2_DATA_DIR`, only ever receives the
result (`record`).

**No model text leaves this service.** A gate compares answers, so it needs
them, but it only needs to know whether two are equal. `answer_fingerprints`
hands back the SHA-256 of each canonical answer, and the comparison
(`domain.qualification.gate_result`) works on those. The seed is synthetic,
so this is habit, not necessity: the same rule then holds wherever this
service is ever pointed (data-handling.md §5).

Every figure is read through the services the Results screens use
(`RankingService`, `ResultsService`), so a qualification scores a model
exactly as an evaluation would. Nothing here re-implements a metric.
"""

import hashlib
import statistics
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId, QualificationId, RecordId, RunId
from ra2.domain.qualification import Qualification, QualitySummary, canonical_answer
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import Extraction, ExtractionEntity, Run
from ra2.persistence.repositories.qualification_repo import QualificationRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import NotFoundError, ServiceError
from ra2.services.ranking_service import RankingService
from ra2.services.readmodels import MetricCell
from ra2.services.results_service import ResultsService

__all__ = ["QualificationService"]

#: One page holds every labelled feature of any feature set RA2 builds.
_ALL_FEATURES = 1000


class QualificationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ranking: RankingService,
        results: ResultsService,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._ranking = ranking
        self._results = results
        self._ids = ids

    # -----------------------------------------------------------------------
    # The throwaway app: read a finished pass back
    # -----------------------------------------------------------------------

    async def quality(self, evaluation_id: EvaluationId) -> QualitySummary:
        """One scored serial pass, as the Results screens would score it.

        The evaluation holds **one** run, the model being qualified. Macro-F1
        and its interval come from the ranking, and the per-language means
        come from the by-language breakdown over the labelled features. A
        suppressed cell is left out, as the Results screen leaves it out.

        :raises ServiceError: the evaluation's run isn't scored, so there is
            nothing honest to record.
        """
        ranking = await self._ranking.ranking_tab(evaluation_id)
        if len(ranking.rows) != 1:
            raise ServiceError(
                f"a qualification pass has exactly one scored run; found {len(ranking.rows)}"
            )
        row = ranking.rows[0]
        run_id = RunId(row.model_id)

        extraction = await self._results.extraction_tab(evaluation_id, page_size=_ALL_FEATURES)
        by_language: dict[str, list[float]] = defaultdict(list)
        for feature in extraction.features.items:
            view = await self._results.by_language(run_id, feature.feature_id)
            for language_row in view.rows:
                if isinstance(language_row.cell, MetricCell):
                    by_language[language_row.language].append(language_row.cell.value)

        async with self._session_factory() as session:
            run = await session.get(Run, run_id)
            assert run is not None, "the ranking just read it"
            reasoning_effort = run.llm_reasoning_effort
            records, parse_failures, completion = await _extraction_counts(session, run_id)
            with_entities = await _records_with_entities(session, run_id)

        return QualitySummary(
            records=records,
            # Nullable only on runs from before SD36; a qualification pass is
            # launched now, so it always has one.
            reasoning_effort=reasoning_effort or "unrecorded",
            macro_f1=row.macro_f1,
            macro_f1_low=row.ci_low,
            macro_f1_high=row.ci_high,
            f1_by_language={
                language: round(statistics.fmean(values), 4)
                for language, values in sorted(by_language.items())
            },
            median_latency_ms=row.median_latency_ms,
            ms_per_record=float(row.ms_per_record),
            median_completion_tokens=(int(statistics.median(completion)) if completion else None),
            entity_fill=round(with_entities / records, 4) if records else 0.0,
            parse_failures=parse_failures,
        )

    async def answer_fingerprints(self, run_id: RunId) -> dict[RecordId, str]:
        """Record -> SHA-256 of the canonical answer, for every committed row.

        The gate asks only whether two passes answered a record the same way,
        so an equality-preserving digest is all that crosses this boundary.
        """
        async with self._session_factory() as session:
            rows = await session.execute(
                select(Extraction.record_id, Extraction.raw_output_text).where(
                    Extraction.run_id == run_id
                )
            )
            return {RecordId(record_id): _fingerprint(raw) for record_id, raw in rows.tuples()}

    async def pass_wall_ms(self, run_id: RunId) -> int:
        """How long the pass took, start to finish. A qualification pass is
        never resumed, so `started_at` wasn't restamped (SD38's caveat).

        :raises NotFoundError: no such run.
        :raises ServiceError: the run never finished.
        """
        async with self._session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            if run.started_at is None or run.finished_at is None:
                raise ServiceError(f"run {run_id} did not finish, so it has no duration")
            return max(1, int((run.finished_at - run.started_at).total_seconds() * 1000))

    # -----------------------------------------------------------------------
    # The target app: keep the result
    # -----------------------------------------------------------------------

    async def record(self, qualification: Qualification) -> QualificationId:
        """Append one qualification. Never replaces one: the newest per
        (tag, digest) wins when read (SD40)."""
        qualification_id = QualificationId(self._ids.new_id())
        async with session_scope(self._session_factory) as session:
            await QualificationRepository(session).add(qualification_id, qualification)
        return qualification_id


def _fingerprint(raw: str) -> str:
    return hashlib.sha256(canonical_answer(raw).encode("utf-8")).hexdigest()


async def _extraction_counts(session: AsyncSession, run_id: RunId) -> tuple[int, int, list[int]]:
    rows = (
        await session.execute(
            select(Extraction.parse_ok, Extraction.completion_tokens).where(
                Extraction.run_id == run_id
            )
        )
    ).tuples()
    records = 0
    parse_failures = 0
    completion: list[int] = []
    for parse_ok, completion_tokens in rows:
        records += 1
        parse_failures += 0 if parse_ok else 1
        if completion_tokens is not None:
            completion.append(completion_tokens)
    return records, parse_failures, completion


async def _records_with_entities(session: AsyncSession, run_id: RunId) -> int:
    stmt = (
        select(func.count(func.distinct(ExtractionEntity.extraction_id)))
        .join(Extraction, Extraction.id == ExtractionEntity.extraction_id)
        .where(Extraction.run_id == run_id)
    )
    return int(await session.scalar(stmt) or 0)
