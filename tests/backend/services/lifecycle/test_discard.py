"""Discard: the two guards, and a cascade that is verified rather than assumed
(plan-reset-and-discard.md §8, sw-design.md §18).

The cascade tests are the ones worth reading twice. SQLite enforces foreign
keys **only** when `foreign_keys=ON` is set per connection (`session.py`'s
connect-time PRAGMA), so a `DELETE` that looks right can silently leave five
tables of orphans on a misconfigured engine. These run against the real
temp-file database with the real engine, and count what went and what stayed.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.lifecycle.conftest import TAGGED, ScoredWorld

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import DeliveryId, EvaluationId, RunId
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    EvaluationFeature,
    Extraction,
    ExtractionEntity,
    ExtractionValue,
    Feature,
    FeatureConfig,
    Mismatch,
    PromptTemplate,
    Run,
    Score,
)
from ra2.services.errors import NotFoundError, RunActiveError, TaggedWorkPresentError
from ra2.services.lifecycle_service import LifecycleService

pytestmark = pytest.mark.backend


async def _count(session: AsyncSession, model: type, *where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)  # type: ignore[arg-type]
    return int(await session.scalar(stmt) or 0)


# --- the preview ----------------------------------------------------------


async def test_preview_counts_what_would_be_lost(
    lifecycle_service: LifecycleService, scored: ScoredWorld
) -> None:
    preview = await lifecycle_service.run_preview(scored.tagged_run_id)

    assert preview.kind == "run"
    assert preview.runs == 1
    assert preview.extractions > 0
    assert preview.scores > 0
    assert preview.mismatches > 0
    assert preview.tagged_mismatches == TAGGED
    assert preview.has_exportable is True
    assert preview.blocked is False


async def test_preview_writes_nothing(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        before = await _count(session, Score)
    await lifecycle_service.run_preview(scored.tagged_run_id)
    async with db_session_factory() as session:
        assert await _count(session, Score) == before


async def test_evaluation_preview_sums_its_runs(
    lifecycle_service: LifecycleService, scored: ScoredWorld
) -> None:
    per_run = [await lifecycle_service.run_preview(r) for r in scored.corpus.run_ids]
    whole = await lifecycle_service.evaluation_preview(scored.corpus.evaluation_id)

    assert whole.runs == len(scored.corpus.run_ids)
    assert whole.extractions == sum(p.extractions for p in per_run)
    assert whole.scores == sum(p.scores for p in per_run)
    assert whole.tagged_mismatches == sum(p.tagged_mismatches for p in per_run)


async def test_missing_run_is_not_found(lifecycle_service: LifecycleService) -> None:
    with pytest.raises(NotFoundError):
        await lifecycle_service.run_preview(RunId("no-such-run"))


# --- G1: nothing active is discarded --------------------------------------


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
async def test_an_active_run_is_refused(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
    status: RunStatus,
) -> None:
    run_id = scored.corpus.run_ids[1]
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = status
        await session.commit()

    with pytest.raises(RunActiveError):
        await lifecycle_service.discard_run(run_id)

    async with db_session_factory() as session:
        assert await session.get(Run, run_id) is not None


@pytest.mark.parametrize("status", [RunStatus.DONE, RunStatus.FAILED, RunStatus.INTERRUPTED])
async def test_every_settled_status_discards(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
    status: RunStatus,
) -> None:
    """An **interrupted** run is exactly the debris this verb exists to clear,
    so it is discardable like the other two (§18.2)."""
    run_id = scored.corpus.run_ids[1]
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = status
        await session.commit()

    await lifecycle_service.discard_run(run_id)

    async with db_session_factory() as session:
        assert await session.get(Run, run_id) is None


async def test_g1_has_no_force_override(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`force` is G2's override and only G2's: deleting the row a worker is
    writing to is not a decision a user gets to take."""
    run_id = scored.corpus.run_ids[1]
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.RUNNING
        await session.commit()

    with pytest.raises(RunActiveError):
        await lifecycle_service.discard_run(run_id, force=True)


async def test_an_evaluation_with_an_active_run_is_refused(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        run = await session.get(Run, scored.corpus.run_ids[1])
        assert run is not None
        run.status = RunStatus.RUNNING
        await session.commit()

    with pytest.raises(RunActiveError):
        await lifecycle_service.discard_evaluation(scored.corpus.evaluation_id, force=True)

    async with db_session_factory() as session:
        assert await session.get(Evaluation, scored.corpus.evaluation_id) is not None


# --- G2: human work is never destroyed silently ---------------------------


async def test_tagged_mismatches_refuse_and_carry_the_count(
    lifecycle_service: LifecycleService, scored: ScoredWorld
) -> None:
    with pytest.raises(TaggedWorkPresentError) as caught:
        await lifecycle_service.discard_run(scored.tagged_run_id)

    assert caught.value.tagged_count == TAGGED
    assert caught.value.kind == "run"


async def test_force_proceeds_through_the_warning(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Warn and allow (`R-D3`): a hard block leaves no way to ever remove the
    run, and pushes people to the database file."""
    await lifecycle_service.discard_run(scored.tagged_run_id, force=True)

    async with db_session_factory() as session:
        assert await session.get(Run, scored.tagged_run_id) is None


async def test_an_untagged_run_needs_no_force(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    untagged = scored.corpus.run_ids[1]
    await lifecycle_service.discard_run(untagged)

    async with db_session_factory() as session:
        assert await session.get(Run, untagged) is None


# --- the cascade is real, not assumed -------------------------------------


async def test_discarding_a_run_takes_its_derived_rows(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = scored.tagged_run_id
    async with db_session_factory() as session:
        extraction_ids = list(
            (await session.scalars(select(Extraction.id).where(Extraction.run_id == run_id))).all()
        )
        assert extraction_ids, "the fixture must produce extractions"
        assert await _count(session, Score, Score.run_id == run_id) > 0
        assert await _count(session, Mismatch, Mismatch.run_id == run_id) > 0
        # Captured, never scored (mvp-spec.md §10.3) — and it still has to go
        # with the run, which is the half of §18.1 a scoring fixture alone
        # would leave untested.
        assert await _count(
            session, ExtractionEntity, ExtractionEntity.id.in_(scored.entity_ids)
        ) == len(scored.entity_ids)

    await lifecycle_service.discard_run(run_id, force=True)

    async with db_session_factory() as session:
        assert await _count(session, Extraction, Extraction.run_id == run_id) == 0
        assert (
            await _count(
                session, ExtractionValue, ExtractionValue.extraction_id.in_(extraction_ids)
            )
            == 0
        )
        assert (
            await _count(session, ExtractionEntity, ExtractionEntity.id.in_(scored.entity_ids)) == 0
        )
        assert await _count(session, Score, Score.run_id == run_id) == 0
        assert await _count(session, Mismatch, Mismatch.run_id == run_id) == 0


async def test_discarding_a_run_leaves_everything_it_cited(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The curated half stays: corpus, features, prompt version, evaluation —
    and the evaluation's **other** run, which is a different experiment."""
    other_run = scored.corpus.run_ids[1]
    await lifecycle_service.discard_run(scored.tagged_run_id, force=True)

    async with db_session_factory() as session:
        assert await session.get(Evaluation, scored.corpus.evaluation_id) is not None
        assert await session.get(Corpus, scored.corpus.corpus_id) is not None
        assert await session.get(FeatureConfig, scored.corpus.feature_config_id) is not None
        assert await _count(session, Feature) > 0
        assert await _count(session, PromptTemplate) > 0
        assert await session.get(Run, other_run) is not None
        assert await _count(session, Extraction, Extraction.run_id == other_run) > 0
        assert await _count(session, Score, Score.run_id == other_run) > 0


async def test_discarding_an_evaluation_takes_its_runs_and_keeps_its_citations(
    lifecycle_service: LifecycleService,
    scored: ScoredWorld,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    evaluation_id: EvaluationId = scored.corpus.evaluation_id
    await lifecycle_service.discard_evaluation(evaluation_id, force=True)

    async with db_session_factory() as session:
        assert await session.get(Evaluation, evaluation_id) is None
        assert await _count(session, Run, Run.evaluation_id == evaluation_id) == 0
        assert (
            await _count(
                session, EvaluationFeature, EvaluationFeature.evaluation_id == evaluation_id
            )
            == 0
        )
        assert await _count(session, Extraction) == 0
        assert await _count(session, Score) == 0
        assert await _count(session, Mismatch) == 0
        # `RESTRICT`, and untouched: discarding an evaluation is not a way to
        # delete a corpus (§18.1).
        assert await session.get(Corpus, scored.corpus.corpus_id) is not None
        assert await session.get(FeatureConfig, scored.corpus.feature_config_id) is not None
        assert await _count(session, PromptTemplate) > 0


# --- export before discard ------------------------------------------------


async def test_run_export_carries_the_analyst_columns(
    lifecycle_service: LifecycleService, scored: ScoredWorld
) -> None:
    view = await lifecycle_service.run_export(scored.tagged_run_id)

    assert view.scores, "a scored run exports its score rows"
    tagged = [m for m in view.mismatches if m.analyst_tag]
    assert len(tagged) == TAGGED
    assert {m.analyst_tag for m in tagged} == {"hallucination"}
    assert all(m.note is not None for m in tagged)
    # Keys, not ids: the file outlives the rows it describes, so an opaque
    # `feature-…` id in it would name nothing. The fixture's ids all carry
    # that prefix, which is what makes this assertion bite.
    assert view.scores
    assert all(not row.feature_key.startswith("feature-") for row in view.scores)
    assert all(not row.feature_key.startswith("feature-") for row in view.mismatches)


async def test_missing_delivery_is_not_found(lifecycle_service: LifecycleService) -> None:
    with pytest.raises(NotFoundError):
        await lifecycle_service.delivery_preview(DeliveryId("no-such-delivery"))
