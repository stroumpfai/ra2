"""`GET /api/v1/census/{corpus_id}/columns` and `/summary` — thin translation
over `CensusService`, driven end-to-end through `httpx.ASGITransport` against
a real migrated SQLite database (sw-design.md §11.2, plan-m0-m5.md §7).

No ORM object crosses into the response: every assertion below checks a wire
field that was field-by-field copied from a `CensusColumnView`/`CensusSummary`
(the read models `CensusService` returns), never re-derived here.
"""

import pytest
from httpx import AsyncClient
from tests.backend.api.census.conftest import SeedCensusCorpus
from tests.fixtures.factories import make_census_input, make_census_table_input

pytestmark = pytest.mark.backend

# Same hand-computed fixture as tests/backend/services/census/test_census_service.py.
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


async def _seed(seed_census_corpus: SeedCensusCorpus, corpus_id: str) -> None:
    census_input = make_census_input(
        record_count=5, tables=[make_census_table_input("unfall", COLUMNS, CELLS)]
    )
    await seed_census_corpus(corpus_id, census_input=census_input, record_count=5)


async def test_list_columns_returns_a_census_page(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed(seed_census_corpus, "corpus-1")

    response = await api_client.get(
        "/api/v1/census/corpus-1/columns", params={"sort_key": "column_name", "sort_dir": "asc"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 4
    assert body["meta"]["page"] == 1
    assert body["meta"]["sort_key"] == "column_name"
    assert body["meta"]["sort_dir"] == "asc"

    by_name = {item["column_name"]: item for item in body["items"]}
    unfall_uid = by_name["UnfallUid"]
    assert unfall_uid["table_name"] == "unfall"
    assert unfall_uid["populated_count"] == 5
    assert unfall_uid["populated_rate"] == pytest.approx(1.0)
    assert unfall_uid["distinct_count"] == 5
    assert unfall_uid["long_tail"] is False
    assert unfall_uid["type_hint"] == "text"
    assert unfall_uid["in_config"] is False
    assert [(v["value_raw"], v["count"]) for v in unfall_uid["top_values"]] == [
        ("u1", 1),
        ("u2", 1),
        ("u3", 1),
        ("u4", 1),
        ("u5", 1),
    ]

    wetter = by_name["WetterAusw"]
    assert wetter["type_hint"] == "enum"
    assert wetter["populated_count"] == 4
    assert wetter["top_value_share"] == pytest.approx(0.75)

    strasse = by_name["StrasseName"]
    assert strasse["populated_count"] == 0
    assert strasse["top_values"] == []


async def test_list_columns_filters_by_table_name(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    census_input = make_census_input(
        record_count=2,
        tables=[
            make_census_table_input("unfall", ("A",), [("A", "1"), ("A", "2")]),
            make_census_table_input("objekt", ("B",), [("B", "1")]),
        ],
    )
    await seed_census_corpus("corpus-2", census_input=census_input, record_count=2)

    response = await api_client.get(
        "/api/v1/census/corpus-2/columns", params={"table_name": "objekt"}
    )

    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["table_name"] == "objekt"


async def test_list_columns_filters_by_min_populated_rate(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed(seed_census_corpus, "corpus-3")

    response = await api_client.get(
        "/api/v1/census/corpus-3/columns", params={"min_populated_rate": 0.9}
    )

    body = response.json()
    assert body["meta"]["total"] == 2
    assert {item["column_name"] for item in body["items"]} == {"UnfallUid", "AnzObjFeld"}


async def test_list_columns_default_sort_is_populated_rate_descending(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed(seed_census_corpus, "corpus-4")

    response = await api_client.get("/api/v1/census/corpus-4/columns")

    body = response.json()
    assert body["meta"]["sort_key"] == "populated_rate"
    assert body["meta"]["sort_dir"] == "desc"
    rates = [item["populated_rate"] for item in body["items"]]
    assert rates == sorted(rates, reverse=True)


async def test_list_columns_pages(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed(seed_census_corpus, "corpus-5")

    page_1 = await api_client.get(
        "/api/v1/census/corpus-5/columns",
        params={"sort_key": "column_name", "sort_dir": "asc", "page": 1, "page_size": 2},
    )
    page_2 = await api_client.get(
        "/api/v1/census/corpus-5/columns",
        params={"sort_key": "column_name", "sort_dir": "asc", "page": 2, "page_size": 2},
    )

    assert page_1.json()["meta"]["total"] == 4
    assert len(page_1.json()["items"]) == 2
    assert page_2.json()["meta"]["page"] == 2
    assert len(page_2.json()["items"]) == 2
    names = {item["column_name"] for item in page_1.json()["items"]} | {
        item["column_name"] for item in page_2.json()["items"]
    }
    assert names == set(COLUMNS)


async def test_list_columns_unknown_corpus_returns_an_empty_page(
    api_client: AsyncClient,
) -> None:
    """No corpus row, no census rows: `CensusRepository` filters by
    `corpus_id` and finds nothing — an empty page, not a 404 (census has no
    existence check of its own; sw-design.md §7 is silent, so the nearest
    pattern — a plain filtered query — wins, per CLAUDE.md's "where it is
    silent, follow the nearest existing pattern")."""
    response = await api_client.get("/api/v1/census/does-not-exist/columns")

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 0
    assert response.json()["items"] == []


async def test_get_summary_returns_buckets_and_table_counts(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed(seed_census_corpus, "corpus-6")

    response = await api_client.get("/api/v1/census/corpus-6/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["corpus_id"] == "corpus-6"
    labels = [b["label"] for b in body["buckets"]]
    assert labels == ["100-80", "80-60", "60-40", "40-20", "20-0", "empty"]
    counts = {b["label"]: b["column_count"] for b in body["buckets"]}
    assert counts["100-80"] == 2
    assert counts["80-60"] == 1
    assert counts["empty"] == 1
    assert body["column_counts_by_table"] == {"unfall": 4}
    assert body["total_column_count"] == 4
