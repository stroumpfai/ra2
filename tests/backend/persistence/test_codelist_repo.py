"""Round-trip tests for `CodelistRepository` against a real temp-file SQLite
database (sw-design.md §14, mvp-spec.md §5/§7).

`code_table_import` / `code_attribute` / `code_value` are additive, never
edited in place (Do-NOT list #2). `column_mapping` is the one editable table
Codelists introduces (§14.2) — it is re-pointed in place, never appended.

`coverage_counts()` is the sharpest test here: sw-design.md §14.2 requires it
to read the *live* EAV cells, not the materialised `census_value` table,
because `census_value` only keeps a column's top 20 values. The fixture below
deliberately exceeds 20 distinct values and seeds a (deliberately wrong,
truncated) `census_value` for the same column, so a query that accidentally
read `census_value` instead of live EAV would fail this test.
"""

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.census import TypeHint
from ra2.domain.ids import (
    CensusColumnId,
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    ObjektRowId,
    PersonRowId,
    RecordId,
)
from ra2.infra.config import Settings
from ra2.persistence.models import (
    CensusColumn,
    CensusValue,
    CodeAttribute,
    CodeTableImport,
    CodeValue,
    ColumnMapping,
    Corpus,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    Record,
    UnfallRow,
)
from ra2.persistence.repositories.codelist_repo import CodelistRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)

#: `w3-green` (phase 1's final tag) has exactly two migrations, head at this
#: revision — the same id D3's phase-2 revision declares as `down_revision`.
_W3_GREEN_HEAD = "a39c30e4559d"


def _make_corpus(corpus_id: str | CorpusId) -> Corpus:
    return Corpus(
        id=CorpusId(corpus_id),
        name=f"corpus {corpus_id}",
        imported_at=NOW,
        version=1,
        source_file_manifest_json="[]",
        import_report_json="[]",
        record_count=0,
        is_dev_sized=False,
        cp1252_canary_count=0,
    )


def _make_record(record_id: str, corpus_id: str | CorpusId, *, unfall_uid: str) -> Record:
    return Record(
        id=RecordId(record_id),
        corpus_id=CorpusId(corpus_id),
        unfall_uid=unfall_uid,
        language="de",
        language_confidence=0.9,
        text_anonymised_flag=False,
    )


# ===========================================================================
# code_table_import / code_attribute / code_value — additive, round-trip
# ===========================================================================


async def test_add_and_get_import_round_trips_attributes_and_values(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import_id = CodeTableImportId("import-1")
    attribute_id = CodeAttributeId("attr-1")

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        code_table_import = CodeTableImport(
            id=import_id,
            source_file="codes-2018.json",
            source_hash="deadbeef",
            imported_at=NOW,
            attributes=[
                CodeAttribute(
                    id=attribute_id,
                    code_table_import_id=import_id,
                    key="accident_type",
                    chapter="4.1.4",
                    name_json='{"de": "Unfalltyp"}',
                    values=[
                        CodeValue(
                            id="cv-1",
                            code_attribute_id=attribute_id,
                            code="01",
                            label_json='{"de": "Frontalkollision"}',
                        ),
                        CodeValue(
                            id="cv-2",
                            code_attribute_id=attribute_id,
                            code="02",
                            label_json='{"de": "Auffahrkollision"}',
                        ),
                    ],
                )
            ],
        )
        await repo.add_import(code_table_import)
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        fetched = await repo.get_import(import_id)

    assert fetched is not None
    assert fetched.source_file == "codes-2018.json"
    assert fetched.source_hash == "deadbeef"
    assert len(fetched.attributes) == 1
    attribute = fetched.attributes[0]
    assert attribute.key == "accident_type"
    assert attribute.chapter == "4.1.4"
    assert {v.code for v in attribute.values} == {"01", "02"}


async def test_get_import_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        assert await repo.get_import(CodeTableImportId("does-not-exist")) is None


async def test_get_latest_import_returns_most_recent_by_imported_at(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    older = CodeTableImport(
        id=CodeTableImportId("import-older"),
        source_file="codes-2017.json",
        source_hash="aaa",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = CodeTableImport(
        id=CodeTableImportId("import-newer"),
        source_file="codes-2018.json",
        source_hash="bbb",
        imported_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.add_import(older)
        await repo.add_import(newer)
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        latest = await repo.get_latest_import()

    assert latest is not None
    assert latest.id == CodeTableImportId("import-newer")


async def test_list_attributes_orders_by_key(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import_id = CodeTableImportId("import-1")
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.add_import(
            CodeTableImport(
                id=import_id,
                source_file="codes-2018.json",
                source_hash="deadbeef",
                imported_at=NOW,
                attributes=[
                    CodeAttribute(
                        id=CodeAttributeId("attr-b"),
                        code_table_import_id=import_id,
                        key="road_type",
                        name_json="{}",
                    ),
                    CodeAttribute(
                        id=CodeAttributeId("attr-a"),
                        code_table_import_id=import_id,
                        key="accident_type",
                        name_json="{}",
                    ),
                ],
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        attributes = await repo.list_attributes(import_id)

    assert [a.key for a in attributes] == ["accident_type", "road_type"]


# ===========================================================================
# column_mapping — the one editable table (§14.2)
# ===========================================================================


async def _seed_attribute(
    db_session_factory: async_sessionmaker[AsyncSession], attribute_id: str
) -> None:
    import_id = CodeTableImportId(f"import-for-{attribute_id}")
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.add_import(
            CodeTableImport(
                id=import_id,
                source_file="codes-2018.json",
                source_hash=attribute_id,
                imported_at=NOW,
                attributes=[
                    CodeAttribute(
                        id=CodeAttributeId(attribute_id),
                        code_table_import_id=import_id,
                        key=attribute_id,
                        name_json="{}",
                    )
                ],
            )
        )
        await session.commit()


async def test_set_mapping_inserts_then_updates_in_place(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attribute(db_session_factory, "attr-old")
    await _seed_attribute(db_session_factory, "attr-new")

    async with db_session_factory() as session:
        session.add(_make_corpus("corpus-1"))
        await session.commit()

    corpus_id = CorpusId("corpus-1")

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.set_mapping(
            ColumnMapping(
                id=ColumnMappingId("map-1"),
                corpus_id=corpus_id,
                source_column="UnfTypAusw",
                code_attribute_id=CodeAttributeId("attr-old"),
                mapped_at=NOW,
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        mapping = await repo.get_mapping(corpus_id, "UnfTypAusw")
        assert mapping is not None
        assert mapping.code_attribute_id == CodeAttributeId("attr-old")
        assert mapping.id == ColumnMappingId("map-1")

    # Re-pointing: same (corpus_id, source_column) pair, a different
    # attribute. This must update the existing row, not insert a second one
    # (the unique constraint would refuse that regardless).
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.set_mapping(
            ColumnMapping(
                id=ColumnMappingId("map-2-unused"),
                corpus_id=corpus_id,
                source_column="UnfTypAusw",
                code_attribute_id=CodeAttributeId("attr-new"),
                mapped_at=datetime(2026, 9, 13, tzinfo=UTC),
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        mappings = await repo.list_mappings(corpus_id)

    assert len(mappings) == 1
    assert mappings[0].id == ColumnMappingId("map-1")
    assert mappings[0].code_attribute_id == CodeAttributeId("attr-new")


async def test_delete_mapping_is_a_noop_for_an_unknown_pair(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.delete_mapping(CorpusId("does-not-exist"), "no-such-column")
        await session.commit()


async def test_delete_mapping_removes_it(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attribute(db_session_factory, "attr-x")
    async with db_session_factory() as session:
        session.add(_make_corpus("corpus-1"))
        await session.commit()
    corpus_id = CorpusId("corpus-1")

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.set_mapping(
            ColumnMapping(
                id=ColumnMappingId("map-1"),
                corpus_id=corpus_id,
                source_column="UnfTypAusw",
                code_attribute_id=CodeAttributeId("attr-x"),
                mapped_at=NOW,
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        await repo.delete_mapping(corpus_id, "UnfTypAusw")
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        assert await repo.get_mapping(corpus_id, "UnfTypAusw") is None


# ===========================================================================
# coverage_counts (sw-design.md §14.2) — the deliberate EAV exception
# ===========================================================================


async def test_coverage_counts_reads_every_value_not_just_the_top_20(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """22 distinct `UnfTypAusw` values, one of them repeated twice. A
    materialised `census_value` for the same column is seeded too, but
    deliberately truncated to only 19 rows (mirroring the real top-20 rule)
    and with a wrong count on every one of them — if `coverage_counts()` read
    `census_value` instead of the live `unfall_row` cells, this test would
    see far fewer than 22 distinct values and the wrong counts."""
    corpus_id = CorpusId("corpus-1")
    column = "UnfTypAusw"

    #: 21 singleton codes, "01".."21", plus "22" appearing twice — 22
    #: distinct values, 23 records/cells total, safely over the top-20 line.
    codes = [f"{i:02d}" for i in range(1, 22)]
    repeated_code = "22"

    async with db_session_factory() as session:
        session.add(_make_corpus(corpus_id))
        for i in range(len(codes)):
            session.add(_make_record(f"record-{i}", corpus_id, unfall_uid=f"{i:032x}"))
        for j in range(2):
            session.add(_make_record(f"record-repeat-{j}", corpus_id, unfall_uid=f"r{j:031x}"))
        await session.flush()

        for i, code in enumerate(codes):
            session.add(
                UnfallRow(record_id=RecordId(f"record-{i}"), column_name=column, value_raw=code)
            )
        for j in range(2):
            session.add(
                UnfallRow(
                    record_id=RecordId(f"record-repeat-{j}"),
                    column_name=column,
                    value_raw=repeated_code,
                )
            )

        #: The deliberately-wrong, truncated `census_value` for the same
        #: column: only 19 of the 22 codes, and an incorrect count on each.
        census_column_id = CensusColumnId("census-col-1")
        session.add(
            CensusColumn(
                id=census_column_id,
                corpus_id=corpus_id,
                table_name="unfall",
                column_name=column,
                type_hint=TypeHint.ENUM,
                record_count=23,
                populated_count=23,
                populated_rate=1.0,
                distinct_count=22,
                top_value_share=2 / 23,
                long_tail=True,
                values=[
                    CensusValue(
                        census_column_id=census_column_id,
                        rank=rank,
                        value_raw=code,
                        count=99,  # deliberately wrong
                        share=99 / 23,
                    )
                    for rank, code in enumerate(codes[:19], start=1)
                ],
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        result = await repo.coverage_counts(corpus_id, table_name="unfall", source_column=column)

    counts = dict(result)
    assert len(counts) == 22, f"expected 22 distinct values, got {len(counts)}: {counts}"
    assert counts[repeated_code] == 2
    for code in codes:
        assert counts[code] == 1
    # Ordering: descending count first, so the repeated code sorts to the top.
    assert result[0] == (repeated_code, 2)


async def test_coverage_counts_scopes_to_the_given_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        session.add(_make_corpus("corpus-1"))
        session.add(_make_corpus("corpus-2"))
        session.add(_make_record("record-1", "corpus-1", unfall_uid="a" * 32))
        session.add(_make_record("record-2", "corpus-2", unfall_uid="b" * 32))
        await session.flush()
        session.add(
            UnfallRow(record_id=RecordId("record-1"), column_name="UnfTypAusw", value_raw="01")
        )
        session.add(
            UnfallRow(record_id=RecordId("record-2"), column_name="UnfTypAusw", value_raw="02")
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        result = await repo.coverage_counts(
            CorpusId("corpus-1"), table_name="unfall", source_column="UnfTypAusw"
        )

    assert result == [("01", 1)]


async def test_coverage_counts_over_objekt_table(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus_id = CorpusId("corpus-1")
    async with db_session_factory() as session:
        session.add(_make_corpus(corpus_id))
        session.add(_make_record("record-1", corpus_id, unfall_uid="a" * 32))
        await session.flush()
        session.add(
            ObjektRow(
                id=ObjektRowId("objekt-1"), record_id=RecordId("record-1"), objekt_uid="b" * 32
            )
        )
        session.add(
            ObjektRow(
                id=ObjektRowId("objekt-2"), record_id=RecordId("record-1"), objekt_uid="c" * 32
            )
        )
        await session.flush()
        session.add(
            ObjektCell(
                objekt_row_id=ObjektRowId("objekt-1"), column_name="ObjArtAusw", value_raw="03"
            )
        )
        session.add(
            ObjektCell(
                objekt_row_id=ObjektRowId("objekt-2"), column_name="ObjArtAusw", value_raw="03"
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        result = await repo.coverage_counts(
            corpus_id, table_name="objekt", source_column="ObjArtAusw"
        )

    assert result == [("03", 2)]


async def test_coverage_counts_over_person_table(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Person hangs off `objekt_row`, not off `record` (mvp-spec.md §4.1) —
    a two-hop join, exactly as `PersonRow`'s docstring in `models.py` warns."""
    corpus_id = CorpusId("corpus-1")
    async with db_session_factory() as session:
        session.add(_make_corpus(corpus_id))
        session.add(_make_record("record-1", corpus_id, unfall_uid="a" * 32))
        await session.flush()
        session.add(
            ObjektRow(
                id=ObjektRowId("objekt-1"), record_id=RecordId("record-1"), objekt_uid="b" * 32
            )
        )
        await session.flush()
        session.add(
            PersonRow(
                id=PersonRowId("person-1"),
                objekt_row_id=ObjektRowId("objekt-1"),
                person_uid="c" * 32,
            )
        )
        session.add(
            PersonRow(
                id=PersonRowId("person-2"),
                objekt_row_id=ObjektRowId("objekt-1"),
                person_uid="d" * 32,
            )
        )
        await session.flush()
        session.add(
            PersonCell(
                person_row_id=PersonRowId("person-1"), column_name="GeschlechtAusw", value_raw="1"
            )
        )
        session.add(
            PersonCell(
                person_row_id=PersonRowId("person-2"), column_name="GeschlechtAusw", value_raw="2"
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        result = await repo.coverage_counts(
            corpus_id, table_name="person", source_column="GeschlechtAusw"
        )

    assert set(result) == {("1", 1), ("2", 1)}


async def test_coverage_counts_rejects_an_unknown_table_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CodelistRepository(session)
        with pytest.raises(ValueError, match="table_name"):
            await repo.coverage_counts(
                CorpusId("corpus-1"), table_name="not-a-table", source_column="x"
            )


# ===========================================================================
# migration sanity: applies on top of a real phase-1-shaped database
# ===========================================================================


def test_migration_applies_starting_from_the_w3_green_revision(
    backend_settings: Settings,
) -> None:
    """`w3-green` (phase 1's final tag) has exactly two migrations, head at
    `a39c30e4559d` — the same id D3's phase-2 revision declares as its
    `down_revision`. Upgrading a fresh DB to precisely that revision first,
    then the rest of the way to `head`, proves this migration applies to a
    real phase-1-shaped database rather than only ever running as part of
    one from-scratch `alembic upgrade head` call (D3's exit criteria).

    Synchronous, like `test_migrations_form_a_single_linear_chain`: `alembic
    upgrade` drives its own event loop internally (`env.py`'s
    `asyncio.run(...)`), which cannot be nested inside a running one — an
    `async def` test under pytest-asyncio already has one.
    """
    repo_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "ra2" / "persistence" / "migrations"))
    cfg.cmd_opts = Namespace(x=[f"url={backend_settings.database_url}"])
    backend_settings.database_path.parent.mkdir(parents=True, exist_ok=True)

    command.upgrade(cfg, _W3_GREEN_HEAD)
    command.upgrade(cfg, "head")

    sync_engine = sa.create_engine(
        f"sqlite:///{backend_settings.database_path}", connect_args={"check_same_thread": False}
    )
    try:
        with sync_engine.connect() as conn:
            table_names = sa.inspect(conn).get_table_names()
    finally:
        sync_engine.dispose()

    for table in (
        "code_table_import",
        "code_attribute",
        "code_value",
        "column_mapping",
        "feature_config",
        "feature",
    ):
        assert table in table_names
