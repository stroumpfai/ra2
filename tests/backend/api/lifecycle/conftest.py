"""Fixtures for the three `DELETE` routes (plan-reset-and-discard.md §8).

The world is `seed_scored_corpus` written straight into the same temp database
`api_app` is wired to, then scored **through the app's own services** — so the
rows the routes discard are the rows the app produces, not a hand-built
imitation of them.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.domain.ids import RunId
from ra2.persistence.models import Mismatch


@dataclass(frozen=True, slots=True)
class ScoredApi:
    corpus: ScoredCorpus
    tagged_run_id: RunId
    untagged_run_id: RunId


@pytest.fixture
async def scored_api(
    api_app: FastAPI,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ScoredApi]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()

    scoring = api_app.state.services.scoring
    for run_id in corpus.run_ids:
        await scoring.score_run(run_id)

    tagged_run_id = corpus.run_ids[0]
    async with db_session_factory() as session:
        row: Mismatch | None = await session.scalar(
            select(Mismatch).where(Mismatch.run_id == tagged_run_id).order_by(Mismatch.id).limit(1)
        )
        assert row is not None
        row.analyst_tag = "structured_data_error"
        await session.commit()

    yield ScoredApi(corpus=corpus, tagged_run_id=tagged_run_id, untagged_run_id=corpus.run_ids[1])
