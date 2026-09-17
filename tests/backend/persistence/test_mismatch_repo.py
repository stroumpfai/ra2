"""`MismatchRepository` (mvp-spec.md §5/§12, sw-design.md §16.6).

**The one mutable row in this pipeline**, and the only repository in the
project whose write has to preserve something. The headline test is the one
that fails if someone replaces the upsert with `DELETE`-then-`INSERT` — which
is shorter, obvious, and destroys an analyst's work silently at the moment a
developer is most confident, because they have just fixed the scorer.

**Phase 5 (W1) adds the mirror half** (sw-design.md §17.1): the scorer's
`upsert_feature` must not clobber review, and review's `set_tag` must not
clobber the scorer. Both are asserted on the row, column by column — a count
would pass a write that rewrote a span with itself minus its accents.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import count

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import LIGHT, WEATHER, ScoredCorpus, seed_scored_corpus

from ra2.domain.ids import MismatchId
from ra2.domain.mismatch import MISMATCH_SORT_KEYS, MismatchTag, TagState, tally
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


# --- Phase 5 (W1): the review side of the split ------------------------------
#
# sw-design.md §17.1. `upsert_feature` above is the scorer's half and is
# unchanged; these are the other half. Two obligations run through all of them:
# `set_tag` writes three columns and touches nothing else, and the list and the
# tally are filtered by the same code so they cannot disagree.

NOW = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)


async def _seed_mismatches(
    session: AsyncSession,
    new_id: Callable[[], str],
    *,
    records: int = 40,
    per_feature: int = 6,
) -> ScoredCorpus:
    """One run, two features, `per_feature` mismatches each, all untagged."""
    seeded = await seed_scored_corpus(session, records=records)
    repo = MismatchRepository(session)
    for key in (WEATHER, LIGHT):
        await repo.upsert_feature(
            seeded.run_ids[0],
            seeded.feature_ids[key],
            [write(seeded.record_ids[i], str(i)) for i in range(per_feature)],
            new_id=new_id,
        )
    await session.commit()
    return seeded


@pytest.mark.asyncio
async def test_the_list_joins_the_feature_key_and_the_anonymisation_flag(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """`MismatchListRow` carries both, out of the same `SELECT`.

    The Feature column shows `feature.key`, and `mvp-spec.md` §13 requires the
    anonymisation marking wherever record text is shown — and this row shows an
    evidence span. Handing a caller bare ORM rows would make a relationship
    walk per row the only way to draw a page, which is the N+1 §17.8 rules out.
    """
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id)
        rows, total = await MismatchRepository(session).list_for(seeded.run_ids[0], limit=100)

    assert total == 12
    assert {row.feature_key for row in rows} == {WEATHER, LIGHT}
    assert all(isinstance(row.anonymised, bool) for row in rows)
    assert all(row.evidence_span == "Schneefall" for row in rows)


@pytest.mark.asyncio
async def test_set_tag_leaves_the_derived_columns_byte_identical(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """**The headline test of this wave** (§17.1, R4).

    The mirror of `test_a_rescore_preserves_the_analysts_tag`: that one proves
    the scorer does not clobber review, this one proves review does not clobber
    the scorer. Asserted **on the row**, column by column, rather than on a
    count — a count would pass an `UPDATE` that rewrote a span with itself
    minus its accents.
    """
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=1)
        repo = MismatchRepository(session)
        (before,), _ = await repo.list_for(seeded.run_ids[0], limit=1)

        after = await repo.set_tag(
            before.id, tag=MismatchTag.HALLUCINATION.value, note="invented", now=NOW
        )
        await session.commit()

    assert after is not None
    assert after.analyst_tag == "hallucination"
    assert after.tagged_at == NOW
    assert after.note == "invented"
    #: Everything the scorer owns, untouched.
    assert after.record_value == before.record_value
    assert after.extracted_value == before.extracted_value
    assert after.evidence_span == before.evidence_span
    assert after.record_id == before.record_id
    assert after.feature_id == before.feature_id


@pytest.mark.asyncio
async def test_clearing_a_tag_clears_the_timestamp_and_the_note_with_it(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """`Q4`. A cleared row that kept its `tagged_at` would read as reviewed in
    the `Reviewed` column while counting as untagged in the tally — the two
    numbers on one screen, disagreeing."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=1)
        repo = MismatchRepository(session)
        (row,), _ = await repo.list_for(seeded.run_ids[0], limit=1)
        await repo.set_tag(row.id, tag="unclear", note="hard to call", now=NOW)
        cleared = await repo.set_tag(row.id, tag=None, note=None, now=NOW)
        await session.commit()

    assert cleared is not None
    assert cleared.analyst_tag is None
    assert cleared.tagged_at is None
    assert cleared.note is None
    assert cleared.evidence_span == "Schneefall", "still the scorer's"


@pytest.mark.asyncio
async def test_set_tag_on_an_unknown_id_returns_none_rather_than_raising(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The repository does not own an HTTP fact. `None` here becomes the
    service's `NotFoundError` and the router's 404."""
    async with db_session_factory() as session:
        await seed_scored_corpus(session)
        await session.commit()
        assert (
            await MismatchRepository(session).set_tag(
                MismatchId("nope"), tag="unclear", note=None, now=NOW
            )
            is None
        )


@pytest.mark.asyncio
async def test_filtering_by_untagged_and_by_a_named_tag_both_round_trip(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """The analyst's work queue is `untagged`; the review of a judgement is one
    named tag. Both are the same closed vocabulary (`TagFilter`)."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=4)
        repo = MismatchRepository(session)
        rows, _ = await repo.list_for(seeded.run_ids[0], limit=100)
        for row in rows[:3]:
            await repo.set_tag(row.id, tag="hallucination", note=None, now=NOW)
        await repo.set_tag(rows[3].id, tag="unclear", note=None, now=NOW)
        await session.commit()

        _, untagged = await repo.list_for(seeded.run_ids[0], tag_state=TagState.UNTAGGED, limit=100)
        _, tagged = await repo.list_for(seeded.run_ids[0], tag_state=TagState.TAGGED, limit=100)
        _, hallucination = await repo.list_for(
            seeded.run_ids[0], tag_state=MismatchTag.HALLUCINATION, limit=100
        )
        _, unclear = await repo.list_for(
            seeded.run_ids[0], tag_state=MismatchTag.UNCLEAR, limit=100
        )
        _, record_error = await repo.list_for(
            seeded.run_ids[0], tag_state=MismatchTag.STRUCTURED_DATA_ERROR, limit=100
        )

    assert (untagged, tagged) == (4, 4)
    assert (hallucination, unclear, record_error) == (3, 1, 0)


@pytest.mark.asyncio
async def test_filtering_by_feature_scopes_the_list_and_the_tally_alike(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """One filter shape for both reads (§17.4), so the strip under the table
    and the table itself cannot end up answering different questions."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=5)
        repo = MismatchRepository(session)
        weather = seeded.feature_ids[WEATHER]

        rows, total = await repo.list_for(seeded.run_ids[0], feature_id=weather, limit=100)
        counts = await repo.tally_for(seeded.run_ids[0], feature_id=weather)

    assert total == 5
    assert {row.feature_key for row in rows} == {WEATHER}
    assert set(counts) == {weather}
    assert tally(counts[weather]).total == 5


@pytest.mark.asyncio
async def test_the_tally_is_one_grouped_query_and_agrees_with_the_list(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """§17.4: one `GROUP BY` per run, never one per feature — and the numbers
    it produces are the ones the list would produce for the same filter."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=6)
        repo = MismatchRepository(session)
        rows, _ = await repo.list_for(seeded.run_ids[0], limit=100)
        for row in rows[:5]:
            await repo.set_tag(row.id, tag="structured_data_error", note=None, now=NOW)
        await session.commit()

        statements = _count_selects(session)
        with statements as seen:
            counts = await repo.tally_for(seeded.run_ids[0])

        _, tagged = await repo.list_for(seeded.run_ids[0], tag_state=TagState.TAGGED, limit=100)

    assert len(seen) == 1, f"{len(seen)} SELECTs for a tally over two features"
    reviewed = sum(tally(per_feature).reviewed for per_feature in counts.values())
    assert reviewed == tagged == 5
    assert sum(tally(per_feature).total for per_feature in counts.values()) == 12


@pytest.mark.asyncio
async def test_an_unrecognised_stored_tag_survives_the_list_and_the_tally(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """`SD24`/R7. Nothing in the MVP writes a fourth tag, so this writes the
    raw string — honest about being a synthetic guarantee.

    What it guards is that neither the list nor the tally quietly loses the
    row: the column is open by design, and a value nobody anticipated has to be
    **visible** rather than absent.
    """
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=2)
        repo = MismatchRepository(session)
        rows, _ = await repo.list_for(seeded.run_ids[0], limit=100)
        await repo.set_tag(rows[0].id, tag="fourth_thing", note=None, now=NOW)
        await session.commit()

        listed, _ = await repo.list_for(seeded.run_ids[0], limit=100)
        counts = await repo.tally_for(seeded.run_ids[0])
        _, tagged = await repo.list_for(seeded.run_ids[0], tag_state=TagState.TAGGED, limit=100)

    stored = next(row for row in listed if row.id == rows[0].id)
    assert stored.analyst_tag == "fourth_thing", "verbatim, never narrowed here"
    totals = [tally(per_feature) for per_feature in counts.values()]
    assert sum(t.other for t in totals) == 1
    assert sum(t.reviewed for t in totals) == 1
    #: "Tagged" means any tag, including one the enum does not name — an
    #: `other` row has been reviewed, whatever the word was.
    assert tagged == 1


@pytest.mark.asyncio
async def test_sorting_is_stable_on_ties_and_pages_without_repeating_a_row(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """Every order ends in the mismatch id, so the sort is **total**.

    Without that, SQLite is free to return equal rows in any order — and
    almost every row here ties, because a run's mismatches share two feature
    keys and, until an analyst starts, one `NULL` tag. Page 2 could then repeat
    a row from page 1 and drop another entirely.
    """
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=6)
        repo = MismatchRepository(session)

        first = [row.id for row in (await repo.list_for(seeded.run_ids[0], limit=100))[0]]
        again = [row.id for row in (await repo.list_for(seeded.run_ids[0], limit=100))[0]]
        assert first == again, "the same query twice returned two orders"

        paged: list[str] = []
        for offset in (0, 5, 10):
            page, total = await repo.list_for(
                seeded.run_ids[0], sort_key="tag", offset=offset, limit=5
            )
            paged.extend(row.id for row in page)

    assert total == 12
    assert len(paged) == 12
    assert len(set(paged)) == 12, "a row appeared on two pages"


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_key", MISMATCH_SORT_KEYS)
async def test_every_sort_key_orders_and_reverses(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
    sort_key: str,
) -> None:
    """C3's four, and there is no fifth. Nothing sorts by "how wrong" — there
    is no such number, and inventing one is §16.9's clustering / agreement /
    sampling deferral arriving as a helpful-looking feature."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=4)
        repo = MismatchRepository(session)
        rows, _ = await repo.list_for(seeded.run_ids[0], limit=100)
        for row, tag in zip(rows, ("unclear", "hallucination", None, ""), strict=False):
            if tag is not None:
                await repo.set_tag(row.id, tag=tag, note=None, now=NOW)
        await session.commit()

        ascending, _ = await repo.list_for(seeded.run_ids[0], sort_key=sort_key, limit=100)
        descending, _ = await repo.list_for(
            seeded.run_ids[0], sort_key=sort_key, descending=True, limit=100
        )

    assert len(ascending) == len(descending) == 8
    assert {row.id for row in ascending} == {row.id for row in descending}
    assert [row.id for row in ascending] != [row.id for row in descending]


@pytest.mark.asyncio
async def test_an_unknown_sort_key_falls_back_rather_than_raising(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """A sort is a rendering input. A stale bookmark should redraw the list,
    not 500 — the closed vocabulary is answered to a caller at the API, where
    a 422 can be explained."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=2)
        repo = MismatchRepository(session)
        fallback, _ = await repo.list_for(seeded.run_ids[0], sort_key="how_wrong", limit=100)
        by_feature, _ = await repo.list_for(seeded.run_ids[0], sort_key="feature", limit=100)

    assert [row.id for row in fallback] == [row.id for row in by_feature]


@pytest.mark.asyncio
async def test_the_list_is_scoped_to_one_run(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """`SD26`, §17.6. There is no evaluation-wide read, because a list mixing
    two models' mismatches for the same record and feature **is** the
    cross-model agreement §16.9 defers."""
    async with db_session_factory() as session:
        seeded = await _seed_mismatches(session, new_id, per_feature=3)
        repo = MismatchRepository(session)
        await repo.upsert_feature(
            seeded.run_ids[1],
            seeded.feature_ids[WEATHER],
            [write(seeded.record_ids[0], "9")],
            new_id=new_id,
        )
        await session.commit()

        _, first = await repo.list_for(seeded.run_ids[0], limit=100)
        _, second = await repo.list_for(seeded.run_ids[1], limit=100)
        second_counts = await repo.tally_for(seeded.run_ids[1])

    assert (first, second) == (6, 1)
    assert sum(tally(per_feature).total for per_feature in second_counts.values()) == 1


@pytest.mark.asyncio
async def test_the_filtered_list_issues_a_bounded_number_of_statements(
    db_session_factory: async_sessionmaker[AsyncSession],
    new_id: Callable[[], str],
) -> None:
    """**R4, one table over.** The bound is a statement count, not a wall-clock
    number, because the latter is flaky on a shared machine.

    A thousand mismatches on one run: one page, one count, and **nothing that
    scales with the row count**. A per-row lookup of `feature.key` or the
    record's anonymisation flag is precisely the regression this guards, and it
    is the one a reviewer would not see in a diff.
    """
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session, records=1000)
        repo = MismatchRepository(session)
        await repo.upsert_feature(
            seeded.run_ids[0],
            seeded.feature_ids[WEATHER],
            [write(seeded.record_ids[i], str(i)) for i in range(1000)],
            new_id=new_id,
        )
        await session.commit()

        with _count_selects(session) as seen:
            rows, total = await repo.list_for(seeded.run_ids[0], limit=25)

    assert total == 1000
    assert len(rows) == 25
    assert len(seen) <= 2, (
        f"{len(seen)} SELECTs to draw 25 rows of 1 000 — this scales with the "
        "run, which is the N+1 R4 warns about"
    )


@contextmanager
def _count_selects(session: AsyncSession) -> Iterator[list[str]]:
    """Every `SELECT` the engine issues inside the block.

    The same instrument `test_ground_truth_repo.py` uses for its own R4 guard,
    and for the same reason: what must not move is the count's *independence*
    from the row count.
    """
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = session.get_bind().engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
