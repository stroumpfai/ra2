"""`GET /api/v1/census/{corpus_id}/export.csv` — asserted byte-wise through
the actual HTTP response, BOM and all (plan-m0-m5.md §7's C2 exit criterion:
"export asserted byte-wise through the API").

The router must not touch `ExportService.census_csv`'s returned bytes in any
way — no re-encode, no decode, no strip. This is the one place that would
silently corrupt the BOM if it did.
"""

import pytest
from httpx import AsyncClient
from tests.backend.api.census.conftest import SeedCensusCorpus
from tests.fixtures.factories import make_census_input, make_census_table_input

from ra2.services.export_service import CSV_BOM, CSV_DELIMITER

pytestmark = pytest.mark.backend


async def _seed_two_column_corpus(
    seed_census_corpus: SeedCensusCorpus, corpus_id: str, *, version: int = 1
) -> None:
    census_input = make_census_input(
        record_count=10,
        tables=[
            make_census_table_input("unfall", ("High", "Low"), [("High", "x")] * 9 + [("Low", "y")])
        ],
    )
    await seed_census_corpus(corpus_id, census_input=census_input, record_count=10, version=version)


async def test_export_csv_is_byte_exact_including_the_bom(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-1")

    response = await api_client.get("/api/v1/census/corpus-1/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    expected = CSV_BOM + (
        b"# corpus corpus-1 v1\r\n"
        b"table_name;column_name;type_hint;record_count;populated_count;"
        b"populated_rate;distinct_count;top_value_share;long_tail;top_values\r\n"
        b"unfall;High;text;10;9;0.9;1;1.0;False;x:9\r\n"
        b"unfall;Low;text;10;1;0.1;1;1.0;False;y:1\r\n"
    )
    assert response.content == expected
    assert response.content.startswith(CSV_BOM)


async def test_export_csv_respects_filter_and_sort_query_params(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-2")

    unfiltered = await api_client.get("/api/v1/census/corpus-2/export.csv")
    filtered = await api_client.get(
        "/api/v1/census/corpus-2/export.csv", params={"min_populated_rate": 0.5}
    )

    def _data_rows(content: bytes) -> list[str]:
        body = content[len(CSV_BOM) :].decode("utf-8")
        return [line for line in body.split("\r\n")[2:] if line]

    unfiltered_rows = _data_rows(unfiltered.content)
    filtered_rows = _data_rows(filtered.content)
    assert len(unfiltered_rows) == 2
    assert len(filtered_rows) == 1
    assert filtered_rows[0].startswith("unfall;High;")


async def test_export_csv_respects_table_name_filter(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    census_input = make_census_input(
        record_count=1,
        tables=[
            make_census_table_input("unfall", ("A",), [("A", "1")]),
            make_census_table_input("objekt", ("B",), [("B", "1")]),
        ],
    )
    await seed_census_corpus("corpus-3", census_input=census_input, record_count=1)

    response = await api_client.get(
        "/api/v1/census/corpus-3/export.csv", params={"table_name": "objekt"}
    )

    body = response.content[len(CSV_BOM) :].decode("utf-8")
    data_lines = [line for line in body.split("\r\n")[2:] if line]
    assert len(data_lines) == 1
    assert data_lines[0].startswith("objekt;B;")


async def test_export_csv_comment_line_names_corpus_id_and_version(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-4", version=3)

    response = await api_client.get("/api/v1/census/corpus-4/export.csv")

    body = response.content[len(CSV_BOM) :].decode("utf-8")
    comment_line = body.split("\r\n")[0]
    assert comment_line == "# corpus corpus-4 v3"


async def test_export_csv_header_uses_semicolon_delimiter(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-5")

    response = await api_client.get("/api/v1/census/corpus-5/export.csv")

    body = response.content[len(CSV_BOM) :].decode("utf-8")
    header = body.split("\r\n")[1]
    assert header.split(CSV_DELIMITER)[0] == "table_name"
