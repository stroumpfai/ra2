"""`MismatchRepository` (mvp-spec.md §5/§12, sw-design.md §16.6).

**The one mutable row in this pipeline**, and the only repository in the
project whose write has to preserve something. The headline test is the one
that fails if someone replaces the upsert with `DELETE`-then-`INSERT` — which
is shorter, obvious, and destroys an analyst's work silently at the moment a
developer is most confident, because they have just fixed the scorer.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import LIGHT, WEATHER, seed_scored_corpus

from ra2.persistence.repositories.mismatch_repo import MismatchRepository, MismatchWrite

TAGGED_AT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def new_id() -> Callable[[], str]:
    """One factory per test, not one per call.

    A fresh counter per call hands two features the same `mismatch-001` and
    violates the primary key — which is the right failure, and is why ids are
    minted once in `services/` from one injected `IdFactory` rather than
    conjured at each call site.
    """
    counter = count(1)
    return lambda: f"mismatch-{next(counter):03d}"


def write(record_id: str, extracted: str) -> MismatchWrite:
    return MismatchWrite(
        record_id=record_id,  # type: ignore[arg-type]
        record_value="1",
        extracted_value=extracted,
        evidence_span="Schneefall",
    )


@pytest.mark.asyncio
async def test_upsert_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = MismatchRepository(session)
        await repo.upsert_feature(
            seeded.run_ids[0],
            seeded.feature_ids[WEATHER],
            [write(seeded.record_ids[0], "2")],
            new_id=new_id,
        )
        await session.commit()

    async with db_session_factory() as session:
        (stored,) = await MismatchRepository(session).for_run(seeded.run_ids[0])
        assert stored.record_value == "1"
        assert stored.extracted_value == "2"
        assert stored.evidence_span == "Schneefall"
        assert stored.analyst_tag is None, "phase 4 writes these and never tags them"


@pytest.mark.asyncio
async def test_a_rescore_preserves_the_analysts_tag(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """**The headline test of this module** (SD21, R5).

    Tagging is the whole of F11. A re-score exists because the *scorer's* code
    can change; the analyst's judgement did not, and rewriting the derived
    columns must leave it standing.
    """
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = MismatchRepository(session)
        feature_id = seeded.feature_ids[WEATHER]
        await repo.upsert_feature(
            seeded.run_ids[0],
            feature_id,
            [write(seeded.record_ids[0], "2")],
            new_id=new_id,
        )
        await session.commit()

        # An analyst reviews it (this is phase 5's job; here it is a hand write).
        (stored,) = await repo.for_run(seeded.run_ids[0])
        stored.analyst_tag = "hallucination"
        stored.tagged_at = TAGGED_AT
        stored.note = "model invented a value"
        await session.commit()

        # Somebody fixes the scorer and re-scores. The extracted value changes.
        await repo.upsert_feature(
            seeded.run_ids[0],
            feature_id,
            [write(seeded.record_ids[0], "3")],
            new_id=new_id,
        )
        await session.commit()

    async with db_session_factory() as session:
        (after,) = await MismatchRepository(session).for_run(seeded.run_ids[0])
        assert after.extracted_value == "3", "the derived column is rewritten"
        assert after.analyst_tag == "hallucination", "the tag survives"
        assert after.tagged_at == TAGGED_AT
        assert after.note == "model invented a value"


@pytest.mark.asyncio
async def test_a_record_that_no_longer_mismatches_loses_its_row(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """Correct, even though it discards a tag: the tag described a mismatch
    that no longer exists, and keeping it would leave review work attached to
    nothing."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = MismatchRepository(session)
        feature_id = seeded.feature_ids[WEATHER]
        await repo.upsert_feature(
            seeded.run_ids[0],
            feature_id,
            [write(seeded.record_ids[0], "2"), write(seeded.record_ids[1], "3")],
            new_id=new_id,
        )
        await session.commit()
        await repo.upsert_feature(
            seeded.run_ids[0],
            feature_id,
            [write(seeded.record_ids[1], "3")],
            new_id=new_id,
        )
        await session.commit()

    async with db_session_factory() as session:
        stored = await MismatchRepository(session).for_run(seeded.run_ids[0])
        assert [m.record_id for m in stored] == [seeded.record_ids[1]]


@pytest.mark.asyncio
async def test_an_upsert_does_not_duplicate_on_the_unique_key(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """`UNIQUE (run_id, record_id, feature_id)` is what makes the upsert
    expressible; this asserts it is actually used rather than worked around."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = MismatchRepository(session)
        feature_id = seeded.feature_ids[WEATHER]
        for _ in range(3):
            await repo.upsert_feature(
                seeded.run_ids[0],
                feature_id,
                [write(seeded.record_ids[0], "2")],
                new_id=new_id,
            )
        await session.commit()
        assert len(await repo.for_run(seeded.run_ids[0])) == 1


@pytest.mark.asyncio
async def test_rewriting_one_feature_leaves_another_features_mismatches_alone(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """The boundary is one `(run, feature)` here too."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = MismatchRepository(session)
        weather, light = seeded.feature_ids[WEATHER], seeded.feature_ids[LIGHT]
        await repo.upsert_feature(
            seeded.run_ids[0],
            weather,
            [write(seeded.record_ids[0], "2")],
            new_id=new_id,
        )
        await repo.upsert_feature(
            seeded.run_ids[0],
            light,
            [write(seeded.record_ids[0], "9")],
            new_id=new_id,
        )
        await repo.upsert_feature(
            seeded.run_ids[0],
            weather,
            [],
            new_id=new_id,
        )
        await session.commit()
        stored = await repo.for_run(seeded.run_ids[0])
        assert [m.feature_id for m in stored] == [light]
