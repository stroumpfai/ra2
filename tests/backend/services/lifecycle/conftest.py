"""Fixtures for discard (plan-reset-and-discard.md §8).

A discard is only interesting over a run that has something to lose, so the
fixture here is `seed_scored_corpus` **plus a real scoring pass**: `score` and
`mismatch` rows written by the scorer, not hand-inserted, so the cascade test
is deleting the rows the app actually produces.

One of those mismatches is then tagged. That single column is what G2 exists
for, and a fixture without it would let the guard rot untested.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from itertools import count

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.domain.ids import ExtractionId, RunId
from ra2.infra.config import Settings
from ra2.infra.filestore import UploadedFileStore
from ra2.persistence.models import Extraction, ExtractionEntity, Mismatch
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.lifecycle_service import LifecycleService
from ra2.services.scoring_service import ScoringService


class _SeededIds:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"mismatch-{next(self._counter):04d}"


class _NullRunner:
    def submit(self, name: str, work: object) -> str:  # pragma: no cover - unused
        raise AssertionError("these tests drive the services directly")


#: G2's count, in the fixture. Two rather than one because the guard reports a
#: number and a fixture with one cannot tell `len(...)` from `1`.
TAGGED = 2


@dataclass(frozen=True, slots=True)
class ScoredWorld:
    """A scored corpus, plus the tagged mismatches G2 is about and the
    per-entity rows §18.1's cascade has to take with the run."""

    corpus: ScoredCorpus
    tagged_run_id: RunId
    tagged_mismatch_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]


@pytest.fixture
def lifecycle_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
) -> LifecycleService:
    return LifecycleService(
        session_factory=db_session_factory,
        upload_store=UploadedFileStore(backend_settings.deliveries_dir, max_bytes=1024 * 1024),
        settings=backend_settings,
    )


@pytest.fixture
def scoring_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: object,
) -> ScoringService:
    return ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=_NullRunner(),  # type: ignore[arg-type]
        clock=frozen_clock,  # type: ignore[arg-type]
        id_factory=_SeededIds(),
    )


@pytest.fixture
async def scored(
    db_session_factory: async_sessionmaker[AsyncSession],
    scoring_service: ScoringService,
) -> AsyncIterator[ScoredWorld]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()

    for run_id in corpus.run_ids:
        await scoring_service.score_run(run_id)

    tagged_run_id = corpus.run_ids[0]
    async with db_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(Mismatch)
                    .where(Mismatch.run_id == tagged_run_id)
                    .order_by(Mismatch.id)
                    .limit(TAGGED)
                )
            ).all()
        )
        assert len(rows) == TAGGED, "the fixture must produce mismatches to tag"
        for row in rows:
            row.analyst_tag = "hallucination"
            row.note = "the text says nothing about the weather"
        mismatch_ids = tuple(str(row.id) for row in rows)

        # `extraction_entity` is captured and never scored (mvp-spec.md §10.3),
        # so the scoring pass writes none — and a cascade assertion over a
        # table that is empty either way proves nothing. These two rows are
        # what make §18.1's test bite.
        extraction_ids = list(
            (
                await session.scalars(
                    select(Extraction.id)
                    .where(Extraction.run_id == tagged_run_id)
                    .order_by(Extraction.id)
                    .limit(2)
                )
            ).all()
        )
        assert extraction_ids, "the fixture must produce extractions"
        entity_ids = tuple(f"entity-{index}" for index, _ in enumerate(extraction_ids))
        for entity_id, extraction_id in zip(entity_ids, extraction_ids, strict=True):
            session.add(
                ExtractionEntity(
                    id=entity_id,
                    extraction_id=ExtractionId(extraction_id),
                    entity_kind="vehicle",
                    entity_ref="G1",
                    attributes_json='{"type": "car"}',
                )
            )
        await session.commit()

    yield ScoredWorld(
        corpus=corpus,
        tagged_run_id=tagged_run_id,
        tagged_mismatch_ids=mismatch_ids,
        entity_ids=entity_ids,
    )
