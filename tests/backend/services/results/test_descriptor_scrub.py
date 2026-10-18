"""Every board says whether its corpus's narratives were scrubbed (`SD65`,
mvp-spec.md §13: "required on every corpus and every result").

Asserted through the boards, as `test_descriptor.py` asserts the rest of the
identity line, so a builder that forgot the fact fails here rather than on
one screen nobody looked at.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus

from ra2.domain.ids import ScrubRulesetId
from ra2.persistence.models import Corpus, ScrubRuleset
from ra2.services.ranking_service import RankingService
from ra2.services.results_service import ResultsService

pytestmark = pytest.mark.backend


async def test_a_corpus_from_before_scrubbing_reads_as_not_scrubbed(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """`seed_scored_corpus` writes its corpus directly, as every corpus before
    scrubbing was frozen: no fingerprint, so the board says *not scrubbed*."""
    descriptor = (await results_service.extraction_tab(scored.evaluation_id)).descriptor
    assert (descriptor.scrubbed, descriptor.scrub_version) == (False, None)


async def test_a_scrubbed_corpus_names_its_rule_set_on_every_board(
    results_service: ResultsService,
    ranking_service: RankingService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Standing in for a freeze, which `ScoredCorpus` does not go through: the
    # three columns a freeze writes, written once before any board is read.
    async with db_session_factory() as session:
        session.add(
            ScrubRuleset(
                id=ScrubRulesetId("rules-3"),
                version=3,
                created_at=datetime(2026, 10, 18, tzinfo=UTC),
                fingerprint="f" * 64,
            )
        )
        await session.flush()
        await session.execute(
            update(Corpus)
            .where(Corpus.id == scored.corpus_id)
            .values(scrub_ruleset_id="rules-3", scrub_fingerprint="a" * 64)
        )
        await session.commit()

    for descriptor in (
        (await results_service.extraction_tab(scored.evaluation_id)).descriptor,
        (await results_service.presence_tab(scored.evaluation_id)).descriptor,
        (await ranking_service.ranking_tab(scored.evaluation_id)).descriptor,
    ):
        assert (descriptor.scrubbed, descriptor.scrub_version) == (True, 3)
