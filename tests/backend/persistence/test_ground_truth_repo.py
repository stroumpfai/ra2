"""`GroundTruthRepository` (sw-design.md §16.2).

Ground truth is where scoring meets the EAV tables, and it is the phase's
performance risk (R4): a 5 000-record corpus x 13 features is 13 queries if the
shape is right and 65 000 if it is not. The last test in this file is the one
that notices.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ALL_EMPTY, LIGHT, RIGHT_OF_WAY, WEATHER, seed_scored_corpus

from ra2.domain.ids import FeatureId
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository


@pytest.mark.asyncio
async def test_a_native_feature_reads_its_source_column(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=10)
        values = await GroundTruthRepository().values_for(
            session, seeded.corpus_id, seeded.feature_ids[WEATHER]
        )
        assert len(values) == 10
        assert values[seeded.record_ids[0]] == "1"
        assert values[seeded.record_ids[3]] == "4"


@pytest.mark.asyncio
async def test_a_sparsely_populated_column_yields_only_its_populated_records(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**`s01`.** `VortrittAusw` exists on 17 records of 40. The other 23 are
    absent from the mapping entirely — they are not labelled cases, and §8.6
    excludes them from the denominator rather than counting them as
    `MISSING`."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=40)
        values = await GroundTruthRepository().values_for(
            session, seeded.corpus_id, seeded.feature_ids[RIGHT_OF_WAY]
        )
        assert len(values) == 17


@pytest.mark.asyncio
async def test_an_all_empty_column_yields_nothing_at_all(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**`s04`.** The column is configured and populated for nobody. It is not
    a feature that scored zero and not one that was suppressed — it has no
    labelled cases, so it produces no `score` rows at all (§16.2)."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=10)
        values = await GroundTruthRepository().values_for(
            session, seeded.corpus_id, seeded.feature_ids[ALL_EMPTY]
        )
        assert values == {}


@pytest.mark.asyncio
async def test_a_derived_feature_is_evaluated_from_the_projection(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**`s09`.** Half the records have two objekt rows and half have none.

    Both are labelled cases: `"2"` and `"0"`. "No objects" is a fact the data
    states, and a record with none must stay in the denominator — the
    distinction §16.2 calls the most consequential in the section.
    """
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=10)
        values = await GroundTruthRepository().values_for(
            session, seeded.corpus_id, seeded.feature_ids["vehicles"]
        )
        assert len(values) == 10, "every record is a labelled case for a derivation"
        assert values[seeded.record_ids[0]] == "2"
        assert values[seeded.record_ids[1]] == "0"
        assert None not in values.values()


@pytest.mark.asyncio
async def test_an_unknown_feature_yields_nothing_rather_than_raising(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A scoring pass walks a whole evaluation; a stale feature id must not
    take the run's other scores down with it."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=5)
        assert (
            await GroundTruthRepository().values_for(
                session, seeded.corpus_id, FeatureId("no-such-feature")
            )
            == {}
        )


@pytest.mark.asyncio
async def test_projections_carry_objekt_and_person_rows_per_record(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=6)
        projections = await GroundTruthRepository().projections_for(session, seeded.corpus_id)
        assert len(projections) == 6
        with_objects = projections[seeded.record_ids[0]]
        assert len(with_objects.objekt_rows) == 2
        assert with_objects.objekt_rows[0]["ObjArtAusw"] == "01"
        # `person` hangs off `objekt` but the projection is flat per record —
        # no derivation in the catalogue crosses that edge (mvp-spec.md §4.1).
        assert len(with_objects.person_rows) == 2
        assert with_objects.person_rows[0]["VerlAusw"] == "2"


@pytest.mark.asyncio
async def test_a_record_with_no_objekt_rows_still_has_a_projection(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Otherwise `count_objects` could not return `"0"` for it, and the record
    would silently leave every derived feature's denominator."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=6)
        projections = await GroundTruthRepository().projections_for(session, seeded.corpus_id)
        empty = projections[seeded.record_ids[1]]
        assert empty.objekt_rows == []
        assert empty.person_rows == []


@pytest.mark.asyncio
async def test_scoring_a_corpus_issues_a_bounded_number_of_statements(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**R4 — the N+1 guard.**

    `SD2`'s lesson (census materialisation) in a new place: reading ground
    truth per record turns a 5 000-record corpus into minutes. The bound is
    asserted as a **statement count**, not a wall-clock number, because the
    latter is flaky on a shared machine.

    Four native features plus one derived one over 60 records: a handful of
    queries, not sixty of them. The exact figure is allowed to move a little —
    what must not move is its independence from the record count.
    """
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=60)
        await session.commit()

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = session.get_bind().engine
        event.listen(engine, "before_cursor_execute", record)
        try:
            repo = GroundTruthRepository()
            for key in (WEATHER, LIGHT, RIGHT_OF_WAY, ALL_EMPTY):
                await repo.values_for(session, seeded.corpus_id, seeded.feature_ids[key])
            await repo.values_for(session, seeded.corpus_id, seeded.feature_ids["vehicles"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

    # One `Feature` lookup plus one scan per native feature, and three for the
    # derived one's projections. Nothing that scales with 60.
    assert len(statements) <= 20, (
        f"{len(statements)} SELECTs for 5 features over 60 records — "
        "this scales with the corpus, which is the N+1 R4 warns about"
    )
