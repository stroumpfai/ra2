"""`RelationalCensusMaterialiser` against a real temp-file SQLite database.

`materialise()` must write inside the *caller's* transaction (never commit,
never open its own session) and its numbers must be exactly what
`ra2.domain.census.compute_census`/`compute_buckets` — A2's already-correct,
already-tested pure functions — would produce for the same input. This suite
never re-derives those numbers by hand; it reuses the same hand-computed
fixture `tests/unit/census/test_compute_census.py` asserts against, so a
materialise() -> CensusRepository round trip is checked against numbers this
file did not invent.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.factories import make_census_input, make_census_table_input, seed_corpus

from ra2.domain.census import TypeHint
from ra2.domain.ids import CorpusId
from ra2.infra.idgen import SeededFactory
from ra2.persistence.repositories.census_repo import CensusRepository
from ra2.services.census_materialiser import RelationalCensusMaterialiser

pytestmark = pytest.mark.backend

# Identical to tests/unit/census/test_compute_census.py's COLUMNS/CELLS: same
# input, so the expected numbers below are the same numbers that file asserts
# by hand, not a re-derivation.
COLUMNS = ("UnfallUid", "WetterAusw", "AnzObjFeld", "StrasseName")
CELLS = [
    ("UnfallUid", "u1"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "1"),
    ("StrasseName", ""),
    ("UnfallUid", "u2"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "2"),
    ("StrasseName", ""),
    ("UnfallUid", "u3"),
    ("WetterAusw", "02"),
    ("AnzObjFeld", "1"),
    ("StrasseName", ""),
    ("UnfallUid", "u4"),
    ("WetterAusw", ""),
    ("AnzObjFeld", "3"),
    ("StrasseName", ""),
    ("UnfallUid", "u5"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "2"),
    ("StrasseName", ""),
]


async def _materialise_fixture(
    db_session_factory: async_sessionmaker[AsyncSession], corpus_id: str
) -> None:
    census_input = make_census_input(
        record_count=5,
        tables=[make_census_table_input("unfall", COLUMNS, CELLS)],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, corpus_id, record_count=5)
        await materialiser.materialise(session, CorpusId(corpus_id), census_input)
        await session.commit()


async def test_materialise_never_commits_its_own_transaction(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The protocol requires writing inside the *caller's* transaction: if the
    caller rolls back instead of committing, nothing must be visible."""
    census_input = make_census_input(
        record_count=5,
        tables=[make_census_table_input("unfall", COLUMNS, CELLS)],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())

    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-rollback", record_count=5)
        await materialiser.materialise(session, CorpusId("corpus-rollback"), census_input)
        await session.rollback()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        _columns, total = await repo.list_columns(
            CorpusId("corpus-rollback"),
            table_name=None,
            min_populated_rate=None,
            sort_key="populated_rate",
            descending=True,
            offset=0,
            limit=25,
        )
    assert total == 0


async def test_materialise_writes_one_census_column_row_per_input_column(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _materialise_fixture(db_session_factory, "corpus-1")

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        rows, total = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name=None,
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )

    assert total == 4
    assert {row.column_name for row in rows} == set(COLUMNS)
    assert all(row.table_name == "unfall" for row in rows)
    assert all(row.record_count == 5 for row in rows)


async def test_a_fully_populated_distinct_column_matches_compute_census(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`UnfallUid`: 5 records, 5 distinct values, each once — the exact
    numbers `test_compute_census.py::test_a_fully_populated_distinct_column`
    hand-computes for the identical input."""
    await _materialise_fixture(db_session_factory, "corpus-2")

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        rows, _total = await repo.list_columns(
            CorpusId("corpus-2"),
            table_name=None,
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )
    by_name = {row.column_name: row for row in rows}
    column = by_name["UnfallUid"]

    assert column.populated_count == 5
    assert column.populated_rate == pytest.approx(1.0)
    assert column.distinct_count == 5
    assert [(v.value_raw, v.count) for v in column.values] == [
        ("u1", 1),
        ("u2", 1),
        ("u3", 1),
        ("u4", 1),
        ("u5", 1),
    ]
    assert all(v.share == pytest.approx(0.2) for v in column.values)
    assert column.top_value_share == pytest.approx(0.2)
    assert column.long_tail is False
    assert column.type_hint == TypeHint.TEXT


async def test_an_ausw_column_with_one_empty_row_matches_compute_census(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`WetterAusw`: populated in 4 of 5 records, `01` three times, `02` once
    — same numbers as `test_compute_census.py::test_an_ausw_column_with_one_empty_row`."""
    await _materialise_fixture(db_session_factory, "corpus-3")

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        rows, _total = await repo.list_columns(
            CorpusId("corpus-3"),
            table_name=None,
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )
    column = {row.column_name: row for row in rows}["WetterAusw"]

    assert column.populated_count == 4
    assert column.populated_rate == pytest.approx(0.8)
    assert column.distinct_count == 2
    assert [(v.value_raw, v.count) for v in column.values] == [("01", 3), ("02", 1)]
    assert [v.share for v in column.values] == [pytest.approx(0.75), pytest.approx(0.25)]
    assert column.top_value_share == pytest.approx(0.75)
    assert column.long_tail is False
    assert column.type_hint == TypeHint.ENUM, "Ausw suffix wins regardless of value shape"


async def test_an_all_empty_column_is_stored_at_zero_percent_not_dropped(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """h08: `StrasseName` is empty in every row but must still be a stored
    row, at 0 % — same as `test_compute_census.py`'s equivalent case."""
    await _materialise_fixture(db_session_factory, "corpus-4")

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        rows, _total = await repo.list_columns(
            CorpusId("corpus-4"),
            table_name=None,
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )
    column = {row.column_name: row for row in rows}["StrasseName"]

    assert column.populated_count == 0
    assert column.populated_rate == 0.0
    assert column.distinct_count == 0
    assert column.values == []
    assert column.top_value_share == 0.0
    assert column.long_tail is False
    assert column.type_hint == TypeHint.TEXT


async def test_materialise_writes_buckets_for_all_six_labels(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`compute_buckets` always returns one entry per `BUCKET_ORDER` label,
    including zero counts; the materialiser must persist all six, not just
    the ones a column actually landed in."""
    await _materialise_fixture(db_session_factory, "corpus-5")

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        buckets = await repo.list_buckets(CorpusId("corpus-5"))

    assert [b.bucket_label for b in buckets] == [
        "100-80",
        "80-60",
        "60-40",
        "40-20",
        "20-0",
        "empty",
    ]
    # UnfallUid (100%) and AnzObjFeld (100%) -> 100-80; WetterAusw sits exactly
    # on the 80% boundary, which `_bucket_label_for` assigns to 80-60, not
    # 100-80; StrasseName (0%, all-empty) -> empty, not 20-0.
    counts = {b.bucket_label: b.column_count for b in buckets}
    assert counts["100-80"] == 2
    assert counts["80-60"] == 1
    assert counts["empty"] == 1
    assert counts["60-40"] == 0
    assert counts["40-20"] == 0
    assert counts["20-0"] == 0


async def test_multiple_tables_are_each_profiled_independently(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    census_input = make_census_input(
        record_count=5,
        tables=[
            make_census_table_input(
                "unfall", ("UnfallUid",), [("UnfallUid", "u1"), ("UnfallUid", "u2")]
            ),
            make_census_table_input(
                "objekt",
                ("ObjektUid",),
                [("ObjektUid", "o1"), ("ObjektUid", "o2"), ("ObjektUid", "o3")],
            ),
        ],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-6", record_count=5)
        await materialiser.materialise(session, CorpusId("corpus-6"), census_input)
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        counts = await repo.count_by_table(CorpusId("corpus-6"))
        objekt_rows, _total = await repo.list_columns(
            CorpusId("corpus-6"),
            table_name="objekt",
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )

    assert counts == {"unfall": 1, "objekt": 1}
    # objekt/person rates use the *record* count as denominator, not the
    # table's own row count (mvp-spec.md: rates stay comparable across
    # tables) — 3 populated ObjektUid cells over 5 records is 60%.
    assert objekt_rows[0].populated_rate == pytest.approx(0.6)


async def test_an_objekt_populated_rate_over_100_percent_is_not_clamped(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A real accident delivery routinely has more `objekt` rows than
    `unfall` records — `unfall.AnzObjFeld` (mvp-spec.md §4.3) exists
    precisely because multi-vehicle accidents are the common case, not the
    exception. `compute_census` uses the record count as every table's
    denominator "so a rate is comparable across tables" (its own docstring,
    and `ra2/domain/census.py` deliberately does not clamp the result) — so a
    well-populated `objekt` column's `populated_rate` legitimately exceeds
    1.0 in real data.

    **Amendment resolved** (`contracts/amendments/feat-m3-census-export.md`):
    `census_column`'s `CheckConstraint` used to reject any value over 1.0,
    which meant `corpus_service.freeze()` would raise `IntegrityError` on
    real deliveries the moment an `objekt` column populated more child rows
    than there are accidents — the *typical* case, not an edge one. The lead
    dropped the upper bound at Wave 2 integration (new migration
    `a39c30e4559d`); this now asserts the real, working behavior.
    """
    census_input = make_census_input(
        record_count=2,
        tables=[
            make_census_table_input(
                "objekt",
                ("ObjektUid",),
                [("ObjektUid", "o1"), ("ObjektUid", "o2"), ("ObjektUid", "o3")],
            )
        ],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-7", record_count=2)
        await materialiser.materialise(session, CorpusId("corpus-7"), census_input)
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        rows, _total = await repo.list_columns(
            CorpusId("corpus-7"),
            table_name="objekt",
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=0,
            limit=25,
        )
    assert rows[0].populated_rate == pytest.approx(1.5)
