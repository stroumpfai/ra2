"""`CensusService.columns`/`.summary` — queries the materialised tables only.

Every assertion here checks that a number came out of the stored
`census_column`/`census_value`/`census_bucket` rows unchanged: `CensusService`
must never re-aggregate EAV cells (sw-design.md §7). The materialise ->
columns/summary round trip reuses the same hand-computed fixture
`tests/unit/census/test_compute_census.py` asserts by hand, so the numbers
below are not this file's own invention.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.factories import make_census_input, make_census_table_input, seed_corpus

from ra2.domain.census import TypeHint
from ra2.domain.ids import CorpusId
from ra2.infra.idgen import SeededFactory
from ra2.persistence.session import create_session_factory
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.census_service import CensusService
from ra2.services.readmodels import SortDir

pytestmark = pytest.mark.backend

# Same fixture as tests/unit/census/test_compute_census.py.
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


@pytest.fixture
def census_service(migrated_engine: AsyncEngine) -> CensusService:
    return CensusService(session_factory=create_session_factory(migrated_engine))


async def _seed_fixture_corpus(
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


async def test_columns_round_trips_the_hand_computed_fixture(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_fixture_corpus(db_session_factory, "corpus-1")

    page = await census_service.columns(
        CorpusId("corpus-1"), sort_key="column_name", sort_dir=SortDir.ASC
    )

    assert page.total == 4
    by_name = {item.column_name: item for item in page.items}

    unfall_uid = by_name["UnfallUid"]
    assert unfall_uid.populated_count == 5
    assert unfall_uid.populated_rate == pytest.approx(1.0)
    assert unfall_uid.distinct_count == 5
    assert [(v.value_raw, v.count) for v in unfall_uid.top_values] == [
        ("u1", 1),
        ("u2", 1),
        ("u3", 1),
        ("u4", 1),
        ("u5", 1),
    ]
    assert unfall_uid.top_value_share == pytest.approx(0.2)
    assert unfall_uid.long_tail is False
    assert unfall_uid.type_hint == TypeHint.TEXT

    wetter = by_name["WetterAusw"]
    assert wetter.populated_count == 4
    assert wetter.populated_rate == pytest.approx(0.8)
    assert wetter.distinct_count == 2
    assert [(v.value_raw, v.count) for v in wetter.top_values] == [("01", 3), ("02", 1)]
    assert wetter.top_value_share == pytest.approx(0.75)
    assert wetter.type_hint == TypeHint.ENUM

    strasse = by_name["StrasseName"]
    assert strasse.populated_count == 0
    assert strasse.populated_rate == 0.0
    assert strasse.top_values == ()


async def test_columns_top_values_come_from_stored_rows_with_no_recomputation(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    """The top-20/top-4/top-3 numbers the UI renders all read straight off
    `CensusColumnView.top_values` — this asserts that tuple is exactly the
    stored `census_value` rows, in rank order, and nothing recomputes a share
    from the raw cells (which `CensusService` never even sees)."""
    await _seed_fixture_corpus(db_session_factory, "corpus-2")

    page = await census_service.columns(
        CorpusId("corpus-2"), table_name="unfall", min_populated_rate=None, sort_key="column_name"
    )
    wetter = next(item for item in page.items if item.column_name == "WetterAusw")

    assert len(wetter.top_values) == 2  # top 20 stored; only 2 distinct values exist
    assert wetter.top_values[0].value_raw == "01"
    assert wetter.top_values[0].count == 3
    assert wetter.top_values[0].share == pytest.approx(0.75)
    assert wetter.top_values[1].value_raw == "02"
    assert wetter.top_values[1].count == 1
    assert wetter.top_values[1].share == pytest.approx(0.25)


async def test_columns_filters_by_table_name(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    census_input = make_census_input(
        record_count=2,
        tables=[
            make_census_table_input("unfall", ("A",), [("A", "1"), ("A", "2")]),
            make_census_table_input("objekt", ("B",), [("B", "1")]),
        ],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-3", record_count=2)
        await materialiser.materialise(session, CorpusId("corpus-3"), census_input)
        await session.commit()

    page = await census_service.columns(CorpusId("corpus-3"), table_name="objekt")

    assert page.total == 1
    assert page.items[0].table_name == "objekt"


async def test_columns_filters_by_min_populated_rate(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_fixture_corpus(db_session_factory, "corpus-4")

    page = await census_service.columns(CorpusId("corpus-4"), min_populated_rate=0.9)

    assert page.total == 2  # UnfallUid and AnzObjFeld, both at 100%
    assert {item.column_name for item in page.items} == {"UnfallUid", "AnzObjFeld"}


async def test_columns_default_sort_is_populated_rate_descending(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_fixture_corpus(db_session_factory, "corpus-5")

    page = await census_service.columns(CorpusId("corpus-5"))

    assert page.sort_key == "populated_rate"
    assert page.sort_dir == SortDir.DESC
    rates = [item.populated_rate for item in page.items]
    assert rates == sorted(rates, reverse=True)
    assert page.items[-1].column_name == "StrasseName"  # 0 % sorts last


async def test_columns_pages(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_fixture_corpus(db_session_factory, "corpus-6")

    page_1 = await census_service.columns(
        CorpusId("corpus-6"), sort_key="column_name", sort_dir=SortDir.ASC, page=1, page_size=2
    )
    page_2 = await census_service.columns(
        CorpusId("corpus-6"), sort_key="column_name", sort_dir=SortDir.ASC, page=2, page_size=2
    )

    assert page_1.total == 4
    assert page_2.total == 4
    assert len(page_1.items) == 2
    assert len(page_2.items) == 2
    assert {item.column_name for item in page_1.items} | {
        item.column_name for item in page_2.items
    } == set(COLUMNS)
    assert page_1.page == 1
    assert page_2.page == 2


async def test_summary_buckets_and_counts_come_from_stored_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_fixture_corpus(db_session_factory, "corpus-7")

    summary = await census_service.summary(CorpusId("corpus-7"))

    assert summary.corpus_id == CorpusId("corpus-7")
    assert [b.label.value for b in summary.buckets] == [
        "100-80",
        "80-60",
        "60-40",
        "40-20",
        "20-0",
        "empty",
    ]
    counts = {b.label.value: b.column_count for b in summary.buckets}
    # UnfallUid (100%) and AnzObjFeld (100%) -> 100-80; WetterAusw (80%,
    # exactly on the boundary) -> 80-60; StrasseName (all-empty) -> empty.
    assert counts["100-80"] == 2
    assert counts["80-60"] == 1
    assert counts["empty"] == 1
    assert summary.column_counts_by_table == {"unfall": 4}
    assert summary.total_column_count == 4
