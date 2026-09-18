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

from ra2.services.export_service import CLASSIFICATION_COMMENT, CSV_BOM, CSV_DELIMITER

pytestmark = pytest.mark.backend

#: Every export opens with the classification line, then the corpus comment,
#: then the header row (risk B1). Named once so a later change to the preamble
#: is one edit here rather than six magic indices scattered through the file.
CLASSIFICATION_LINE = 0
COMMENT_LINE = 1
HEADER_LINE = 2
FIRST_DATA_LINE = 3


def body_lines(content: bytes) -> list[str]:
    return content[len(CSV_BOM) :].decode("utf-8").split("\r\n")


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


async def _seed_coded_and_uncoded(seed_census_corpus: SeedCensusCorpus, corpus_id: str) -> None:
    """One `Ausw`-suffixed column and one that is not.

    The suffix is the delivery's own marking that a column holds codes
    (mvp-spec.md §4.1), and it is what the sample rule reads — so these two
    rows are the whole of risk B1 in one file: the code keeps its values, the
    coordinate does not.
    """
    census_input = make_census_input(
        record_count=4,
        tables=[
            make_census_table_input(
                "unfall",
                ("UnfTypAusw", "Koordinate X"),
                [("UnfTypAusw", "5")] * 3
                + [("UnfTypAusw", "3")]
                + [("Koordinate X", f"26{n}144.5") for n in range(4)],
            )
        ],
    )
    await seed_census_corpus(corpus_id, census_input=census_input, record_count=4)


async def test_export_csv_is_byte_exact_including_the_bom(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-1")

    response = await api_client.get("/api/v1/census/corpus-1/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    expected = CSV_BOM + (
        b"# SENSITIVE \xe2\x80\x94 derived from non-anonymised police accident records.\r\n"
        b"# corpus corpus-1 v1\r\n"
        b"table_name;column_name;type_hint;record_count;populated_count;"
        b"populated_rate;distinct_count;top_value_share;long_tail;top_values;"
        b"top_values_withheld\r\n"
        b"unfall;High;text;10;9;0.9;1;1.0;False;;True\r\n"
        b"unfall;Low;text;10;1;0.1;1;1.0;False;;True\r\n"
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
        return [line for line in body_lines(content)[FIRST_DATA_LINE:] if line]

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

    data_lines = [line for line in body_lines(response.content)[FIRST_DATA_LINE:] if line]
    assert len(data_lines) == 1
    assert data_lines[0].startswith("objekt;B;")


async def test_export_csv_comment_line_names_corpus_id_and_version(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-4", version=3)

    response = await api_client.get("/api/v1/census/corpus-4/export.csv")

    lines = body_lines(response.content)
    assert lines[COMMENT_LINE] == "# corpus corpus-4 v3"


async def test_export_csv_header_uses_semicolon_delimiter(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    await _seed_two_column_corpus(seed_census_corpus, "corpus-5")

    response = await api_client.get("/api/v1/census/corpus-5/export.csv")

    header = body_lines(response.content)[HEADER_LINE]
    assert header.split(CSV_DELIMITER)[0] == "table_name"


# ===========================================================================
# Risk B1 — whose values leave the machine, and what the file says it is
# ===========================================================================


async def test_a_coded_column_keeps_its_values_and_an_uncoded_one_does_not(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    """The finding, in two rows.

    The reviewer measured four `Koordinate` columns and three UID columns
    holding 20 stored values each, 16 to 20 of them occurring exactly once — a
    coordinate that occurs once is one accident, at metre precision, in a file
    whose entire purpose is to be shown to other people.
    """
    await _seed_coded_and_uncoded(seed_census_corpus, "corpus-b1")

    rows = [
        line
        for line in body_lines(
            (await api_client.get("/api/v1/census/corpus-b1/export.csv")).content
        )[FIRST_DATA_LINE:]
        if line
    ]

    coded = next(row for row in rows if ";UnfTypAusw;" in row)
    uncoded = next(row for row in rows if ";Koordinate X;" in row)
    assert coded.endswith(";5:3|3:1;False")
    assert uncoded.endswith(";;True")
    assert "144.5" not in uncoded


async def test_the_aggregates_survive_the_suppression(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    """Only the raw values are withheld.

    Populated count, rate, distinct count, top-value share, long-tail flag and
    type hint are what feature selection actually reads (mvp-spec.md §6), and
    a rule that took those too would have made the deliverable useless rather
    than safe.
    """
    await _seed_coded_and_uncoded(seed_census_corpus, "corpus-b2")

    rows = [
        line
        for line in body_lines(
            (await api_client.get("/api/v1/census/corpus-b2/export.csv")).content
        )[FIRST_DATA_LINE:]
        if line
    ]
    uncoded = next(row for row in rows if ";Koordinate X;" in row).split(CSV_DELIMITER)

    table, column, type_hint, record_count, populated_count = uncoded[:5]
    assert (table, column, type_hint) == ("unfall", "Koordinate X", "decimal")
    assert (record_count, populated_count) == ("4", "4")
    assert uncoded[6] == "4", "distinct_count must survive"


async def test_a_withheld_sample_is_told_apart_from_an_empty_column(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    """`top_values` is empty in both cases and they mean opposite things.

    An all-empty column is a real delivered state (hazard h08) and says "do not
    pick this as a feature". A withheld sample says nothing about the column's
    usefulness at all. Without the flag a reader cannot tell which they hold.
    """
    census_input = make_census_input(
        record_count=2,
        tables=[
            make_census_table_input(
                "unfall",
                ("Koordinate X", "AlwaysEmptyFeld"),
                [("Koordinate X", "2601234.5"), ("Koordinate X", "2609876.5")],
            )
        ],
    )
    await seed_census_corpus("corpus-b3", census_input=census_input, record_count=2)

    rows = [
        line
        for line in body_lines(
            (await api_client.get("/api/v1/census/corpus-b3/export.csv")).content
        )[FIRST_DATA_LINE:]
        if line
    ]

    withheld = next(row for row in rows if ";Koordinate X;" in row)
    empty = next(row for row in rows if ";AlwaysEmptyFeld;" in row)
    assert withheld.endswith(";;True")
    assert empty.endswith(";;False")


async def test_every_export_opens_with_the_classification_line(
    api_client: AsyncClient, seed_census_corpus: SeedCensusCorpus
) -> None:
    """N1 governs the application; nothing governed its outputs.

    The line is written in `_write_csv`, the one place all six exports pass
    through, so it is guaranteed rather than remembered. It is first because
    the first line of a file is the one a reader sees before deciding what to
    do with it.
    """
    await _seed_two_column_corpus(seed_census_corpus, "corpus-b4")

    response = await api_client.get("/api/v1/census/corpus-b4/export.csv")

    assert body_lines(response.content)[CLASSIFICATION_LINE] == CLASSIFICATION_COMMENT
    assert CLASSIFICATION_COMMENT.startswith("# ")
    assert "SENSITIVE" in CLASSIFICATION_COMMENT
