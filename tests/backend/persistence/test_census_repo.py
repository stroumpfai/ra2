"""Round-trip tests for `CensusRepository` against a real temp-file SQLite
database. The materialised census (SD2) is write-once, at corpus freeze."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.census import TypeHint
from ra2.domain.ids import CensusColumnId, CorpusId
from ra2.persistence.models import CensusBucketRow, CensusColumn, CensusValue, Corpus
from ra2.persistence.repositories.census_repo import CensusRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


async def _seed_corpus(session: AsyncSession, corpus_id: str) -> None:
    session.add(
        Corpus(
            id=CorpusId(corpus_id),
            name=f"corpus {corpus_id}",
            imported_at=NOW,
            version=1,
            source_file_manifest_json="[]",
            import_report_json="[]",
            record_count=100,
            is_dev_sized=False,
            cp1252_canary_count=0,
        )
    )
    await session.flush()


def _make_column(
    column_id: str,
    corpus_id: str,
    *,
    table_name: str = "unfall",
    column_name: str = "KantonAusw",
    populated_rate: float = 1.0,
    distinct_count: int = 5,
    with_values: bool = True,
) -> CensusColumn:
    column = CensusColumn(
        id=CensusColumnId(column_id),
        corpus_id=CorpusId(corpus_id),
        table_name=table_name,
        column_name=column_name,
        type_hint=TypeHint.ENUM,
        record_count=100,
        populated_count=int(populated_rate * 100),
        populated_rate=populated_rate,
        distinct_count=distinct_count,
        top_value_share=0.4,
        long_tail=False,
    )
    if with_values:
        column.values = [
            CensusValue(rank=1, value_raw="AG", count=40, share=0.4),
            CensusValue(rank=2, value_raw="BE", count=30, share=0.3),
        ]
    return column


async def test_add_all_and_list_columns_round_trips_values(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        column = _make_column("col-1", "corpus-1")
        await repo.add_all([column], [])
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        columns, total = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name=None,
            min_populated_rate=None,
            sort_key="populated_rate",
            descending=True,
            offset=0,
            limit=25,
        )

    assert total == 1
    assert len(columns) == 1
    fetched = columns[0]
    assert fetched.id == CensusColumnId("col-1")
    assert fetched.column_name == "KantonAusw"
    assert fetched.type_hint == TypeHint.ENUM
    assert [v.value_raw for v in fetched.values] == ["AG", "BE"]
    assert [v.rank for v in fetched.values] == [1, 2]


async def test_list_columns_filters_by_table_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        await repo.add_all(
            [
                _make_column("col-unfall", "corpus-1", table_name="unfall"),
                _make_column(
                    "col-objekt", "corpus-1", table_name="objekt", column_name="ObjArtAusw"
                ),
            ],
            [],
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        columns, total = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name="objekt",
            min_populated_rate=None,
            sort_key="populated_rate",
            descending=True,
            offset=0,
            limit=25,
        )

    assert total == 1
    assert columns[0].table_name == "objekt"


async def test_list_columns_filters_by_min_populated_rate(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        await repo.add_all(
            [
                _make_column(
                    "col-high",
                    "corpus-1",
                    column_name="High",
                    populated_rate=0.9,
                    with_values=False,
                ),
                _make_column(
                    "col-low", "corpus-1", column_name="Low", populated_rate=0.1, with_values=False
                ),
            ],
            [],
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        columns, total = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name=None,
            min_populated_rate=0.5,
            sort_key="populated_rate",
            descending=True,
            offset=0,
            limit=25,
        )

    assert total == 1
    assert columns[0].column_name == "High"


async def test_list_columns_sorts_and_pages(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        await repo.add_all(
            [
                _make_column(
                    "col-a", "corpus-1", column_name="A", populated_rate=0.3, with_values=False
                ),
                _make_column(
                    "col-b", "corpus-1", column_name="B", populated_rate=0.7, with_values=False
                ),
                _make_column(
                    "col-c", "corpus-1", column_name="C", populated_rate=0.5, with_values=False
                ),
            ],
            [],
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        page_1, total = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name=None,
            min_populated_rate=None,
            sort_key="populated_rate",
            descending=True,
            offset=0,
            limit=2,
        )
        page_2, _ = await repo.list_columns(
            CorpusId("corpus-1"),
            table_name=None,
            min_populated_rate=None,
            sort_key="populated_rate",
            descending=True,
            offset=2,
            limit=2,
        )

    assert total == 3
    assert [c.column_name for c in page_1] == ["B", "C"]
    assert [c.column_name for c in page_2] == ["A"]


async def test_list_buckets_round_trips_in_bucket_order(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        buckets = [
            CensusBucketRow(corpus_id=CorpusId("corpus-1"), bucket_label="empty", column_count=1),
            CensusBucketRow(corpus_id=CorpusId("corpus-1"), bucket_label="100-80", column_count=10),
            CensusBucketRow(corpus_id=CorpusId("corpus-1"), bucket_label="20-0", column_count=2),
        ]
        await repo.add_all([], buckets)
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        fetched = await repo.list_buckets(CorpusId("corpus-1"))

    assert [b.bucket_label for b in fetched] == ["100-80", "20-0", "empty"]


async def test_count_by_table_groups_columns(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus(session, "corpus-1")
        repo = CensusRepository(session)
        await repo.add_all(
            [
                _make_column(
                    "col-1", "corpus-1", table_name="unfall", column_name="A", with_values=False
                ),
                _make_column(
                    "col-2", "corpus-1", table_name="unfall", column_name="B", with_values=False
                ),
                _make_column(
                    "col-3", "corpus-1", table_name="objekt", column_name="C", with_values=False
                ),
            ],
            [],
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CensusRepository(session)
        counts = await repo.count_by_table(CorpusId("corpus-1"))

    assert counts == {"unfall": 2, "objekt": 1}
