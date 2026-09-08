"""`ExportService.census_csv` / `.findings_csv` — asserted byte-wise.

Every export is UTF-8 with a BOM (N3, Excel on Windows), `;`-delimited, and
carries a header comment line before the column header row (sw-design.md §7).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.factories import (
    StubCorpusService,
    StubDeliveryService,
    make_census_input,
    make_census_table_input,
    make_delivery_file_view,
    make_delivery_view,
    make_finding,
    seed_corpus,
)

from ra2.domain.findings import FindingCode, Severity
from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.infra.idgen import SeededFactory
from ra2.persistence.session import create_session_factory
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.census_service import CensusService
from ra2.services.errors import NotFoundError
from ra2.services.export_service import CSV_BOM, CSV_DELIMITER, ExportService
from ra2.services.readmodels import DeliveryView

pytestmark = pytest.mark.backend


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


async def _seed_two_column_corpus(
    db_session_factory: async_sessionmaker[AsyncSession], corpus_id: str, *, version: int = 1
) -> None:
    """`High` at 90 %, `Low` at 10 % — enough to prove filter+sort in the
    export without dragging in the whole hand-computed fixture."""
    census_input = make_census_input(
        record_count=10,
        tables=[
            make_census_table_input(
                "unfall",
                ("High", "Low"),
                [("High", "x")] * 9 + [("Low", "y")],
            )
        ],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, corpus_id, record_count=10, version=version)
        await materialiser.materialise(session, CorpusId(corpus_id), census_input)
        await session.commit()


@pytest.fixture
def census_service(migrated_engine: AsyncEngine) -> CensusService:
    return CensusService(session_factory=create_session_factory(migrated_engine))


def _export_service(
    census_service: CensusService, delivery_view: DeliveryView | None = None
) -> ExportService:
    delivery_service = StubDeliveryService(delivery_view or make_delivery_view("unused"))
    # Reaches CensusService's own session_factory rather than threading a
    # separate fixture through every call site — same real temp-file DB
    # either way. Not a frozen file: this is this test module's own helper.
    corpus_service = StubCorpusService(census_service._session_factory)
    return ExportService(
        census_service=census_service,
        delivery_service=delivery_service,
        corpus_service=corpus_service,
        clock=FrozenClock(datetime(2026, 9, 2, 9, 30, tzinfo=UTC)),
    )


# --- census_csv --------------------------------------------------------------


async def test_census_csv_is_utf8_with_bom_and_semicolon_delimiter(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_two_column_corpus(db_session_factory, "corpus-1")
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-1"))

    assert csv_bytes.startswith(CSV_BOM)
    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    lines = body.split("\r\n")
    assert lines[0].startswith("# corpus corpus-1")
    header = lines[1]
    assert header.split(CSV_DELIMITER)[0] == "table_name"
    assert CSV_DELIMITER in header


async def test_census_csv_comment_line_names_corpus_id_and_version(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_two_column_corpus(db_session_factory, "corpus-2", version=3)
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-2"))

    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    comment_line = body.split("\r\n")[0]
    assert comment_line == "# corpus corpus-2 v3"


async def test_census_csv_exact_bytes_unfiltered(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_two_column_corpus(db_session_factory, "corpus-3")
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-3"))

    expected = CSV_BOM + (
        b"# corpus corpus-3 v1\r\n"
        b"table_name;column_name;type_hint;record_count;populated_count;"
        b"populated_rate;distinct_count;top_value_share;long_tail;top_values\r\n"
        b"unfall;High;text;10;9;0.9;1;1.0;False;x:9\r\n"
        b"unfall;Low;text;10;1;0.1;1;1.0;False;y:1\r\n"
    )
    assert csv_bytes == expected


async def test_census_csv_filtered_and_sorted_differs_from_unfiltered_by_exactly_the_expected_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    await _seed_two_column_corpus(db_session_factory, "corpus-4")
    export_service = _export_service(census_service)

    unfiltered = await export_service.census_csv(CorpusId("corpus-4"))
    filtered = await export_service.census_csv(CorpusId("corpus-4"), min_populated_rate=0.5)

    def _data_rows(csv_bytes: bytes) -> list[str]:
        body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
        # drop the comment line and the header row, and the trailing blank
        # line the final "\r\n" produces on split.
        return [line for line in body.split("\r\n")[2:] if line]

    unfiltered_rows = _data_rows(unfiltered)
    filtered_rows = _data_rows(filtered)

    assert len(unfiltered_rows) == 2
    assert len(filtered_rows) == 1
    assert filtered_rows[0].startswith("unfall;High;")
    # The only difference is the excluded `Low` row — every other byte of the
    # surviving row is identical between the two exports.
    assert filtered_rows[0] in unfiltered_rows
    assert set(unfiltered_rows) - set(filtered_rows) == {
        row for row in unfiltered_rows if row.startswith("unfall;Low;")
    }


async def test_census_csv_respects_table_name_filter(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    census_input = make_census_input(
        record_count=1,
        tables=[
            make_census_table_input("unfall", ("A",), [("A", "1")]),
            make_census_table_input("objekt", ("B",), [("B", "1")]),
        ],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-5", record_count=1)
        await materialiser.materialise(session, CorpusId("corpus-5"), census_input)
        await session.commit()
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-5"), table_name="objekt")

    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    data_lines = [line for line in body.split("\r\n")[2:] if line]
    assert len(data_lines) == 1
    assert data_lines[0].startswith("objekt;B;")


async def test_census_csv_gathers_every_page_when_the_corpus_has_many_columns(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
) -> None:
    """Exports have no paging: even though `CensusService.columns` pages
    internally, `census_csv` must return every matching row, not page 1."""
    columns = tuple(f"Col{i}" for i in range(60))
    cells = [(name, "x") for name in columns]
    census_input = make_census_input(
        record_count=1, tables=[make_census_table_input("unfall", columns, cells)]
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-6", record_count=1)
        await materialiser.materialise(session, CorpusId("corpus-6"), census_input)
        await session.commit()
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-6"))

    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    data_lines = [line for line in body.split("\r\n")[2:] if line]
    assert len(data_lines) == 60


async def test_census_csv_walks_multiple_pages_when_the_page_size_is_small(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_service: CensusService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forces `_all_census_columns` through more than one
    `CensusService.columns` round trip, by shrinking the internal page size
    rather than seeding a 1000+-column corpus."""
    monkeypatch.setattr("ra2.services.export_service._EXPORT_PAGE_SIZE", 2)
    columns = ("A", "B", "C", "D", "E")
    census_input = make_census_input(
        record_count=1,
        tables=[make_census_table_input("unfall", columns, [(name, "x") for name in columns])],
    )
    materialiser = RelationalCensusMaterialiser(ids=SeededFactory())
    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-7", record_count=1)
        await materialiser.materialise(session, CorpusId("corpus-7"), census_input)
        await session.commit()
    export_service = _export_service(census_service)

    csv_bytes = await export_service.census_csv(CorpusId("corpus-7"))

    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    data_lines = [line for line in body.split("\r\n")[2:] if line]
    assert len(data_lines) == 5
    assert {line.split(";")[1] for line in data_lines} == set(columns)


# --- findings_csv --------------------------------------------------------------


async def test_findings_csv_is_utf8_with_bom_and_semicolon_delimiter(
    census_service: CensusService,
) -> None:
    finding = make_finding(
        FindingCode.ROW_REJECTED_FIELD_COUNT,
        severity=Severity.REPORTED,
        key="abc123",
        line_no=42,
        detail={"expected_fields": "67", "actual_fields": "68"},
    )
    file_view = make_delivery_file_view("file-1", findings=[finding])
    delivery_view = make_delivery_view("delivery-1", files=[file_view])
    export_service = _export_service(census_service, delivery_view)

    csv_bytes = await export_service.findings_csv(DeliveryId("delivery-1"), FileId("file-1"))

    assert csv_bytes.startswith(CSV_BOM)
    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    lines = body.split("\r\n")
    assert lines[0] == "# delivery delivery-1 file file-1"
    assert lines[1] == "code;severity;key;line_no;detail"
    assert (
        lines[2]
        == "ROW_REJECTED_FIELD_COUNT;REPORTED;abc123;42;actual_fields=68|expected_fields=67"
    )


async def test_findings_csv_exact_bytes_one_row_per_finding(
    census_service: CensusService,
) -> None:
    findings = [
        make_finding(
            FindingCode.ROW_RECOVERED, key="k1", line_no=3, detail={"continuation_lines": "2"}
        ),
        make_finding(FindingCode.ORPHAN_FK, severity=Severity.BLOCKING, key="k2"),
    ]
    file_view = make_delivery_file_view("file-1", findings=findings)
    delivery_view = make_delivery_view("delivery-1", files=[file_view])
    export_service = _export_service(census_service, delivery_view)

    csv_bytes = await export_service.findings_csv(DeliveryId("delivery-1"), FileId("file-1"))

    expected = CSV_BOM + (
        b"# delivery delivery-1 file file-1\r\n"
        b"code;severity;key;line_no;detail\r\n"
        b"ROW_RECOVERED;REPORTED;k1;3;continuation_lines=2\r\n"
        b"ORPHAN_FK;BLOCKING;k2;;\r\n"
    )
    assert csv_bytes == expected


async def test_findings_csv_raises_not_found_for_an_unknown_file(
    census_service: CensusService,
) -> None:
    delivery_view = make_delivery_view("delivery-1", files=[])
    export_service = _export_service(census_service, delivery_view)

    with pytest.raises(NotFoundError):
        await export_service.findings_csv(DeliveryId("delivery-1"), FileId("missing"))


async def test_findings_csv_never_writes_a_preformatted_sentence(
    census_service: CensusService,
) -> None:
    """`Finding.detail` is structured data; the CSV must carry the raw
    key=value pairs, never message text (sw-design.md §5)."""
    finding = make_finding(
        FindingCode.CP1252_CANARY_ZERO, detail={"canary_count": "0", "languages": "de,fr,it"}
    )
    file_view = make_delivery_file_view("file-1", findings=[finding])
    delivery_view = make_delivery_view("delivery-1", files=[file_view])
    export_service = _export_service(census_service, delivery_view)

    csv_bytes = await export_service.findings_csv(DeliveryId("delivery-1"), FileId("file-1"))

    body = csv_bytes[len(CSV_BOM) :].decode("utf-8")
    data_row = body.split("\r\n")[2]
    assert "canary_count=0" in data_row
    assert "languages=de,fr,it" in data_row
    assert "zero" not in data_row.lower().replace("cp1252_canary_zero", "")
