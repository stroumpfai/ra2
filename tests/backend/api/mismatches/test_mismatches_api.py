"""`/api/v1/.../mismatches` (Y2, plan-phase-5.md §9, sw-design.md §17).

Three things this layer is responsible for and nothing below it can guarantee:

- **An evaluation with no mismatches is 200 with an empty list**, never a 404.
  "Nothing was wrong" is a result, and a status code forces a toast where the
  page should simply be in a state (the §16.7 reasoning, reapplied).
- **An unknown tag is 422**, not a silent write. The column is open so a fourth
  tag needs no migration; the wire is closed so nothing in this codebase
  creates one (`SD24`, §17.5). Only the boundary can enforce that half.
- **The CSV streams with the BOM** (N3), because Excel on Windows cannot read
  UTF-8 without it and a CSV is read somewhere this app cannot see.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus

from ra2.services.export_service import CLASSIFICATION_COMMENT, CSV_BOM

pytestmark = pytest.mark.backend


async def _first_mismatch(api_client: AsyncClient, scored: ScoredCorpus) -> dict[str, Any]:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
    )
    assert response.status_code == 200
    rows: list[dict[str, Any]] = response.json()["rows"]["items"]
    assert rows, "the fixture's wrong answers must produce mismatches"
    return rows[0]


# --- the list ---------------------------------------------------------------


async def test_the_list_is_200_with_the_rows_the_scorer_wrote(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/mismatches")
    assert response.status_code == 200
    body = response.json()

    assert body["rows"]["total"] > 0
    assert body["run_label"].startswith("run 1 · ")
    assert len(body["runs"]) == 2
    row = body["rows"]["items"][0]
    #: §12's own list, plus §13's marking — the span is record text.
    for field in ("record_value", "extracted_value", "evidence_span", "anonymised"):
        assert field in row
    assert row["analyst_tag"] is None
    assert row["reviewed"] is False


async def test_an_evaluation_with_no_mismatches_is_200_with_an_empty_list(
    api_client: AsyncClient, unscored: ScoredCorpus
) -> None:
    """**Never a 404** (§16.7, reapplied at §17.6).

    Nothing has been scored, so there are no `mismatch` rows — and "nothing was
    wrong" is a *good* result. An error status would force a toast, and a toast
    is the wrong shape for a state the page should simply be in.
    """
    response = await api_client.get(f"/api/v1/evaluations/{unscored.evaluation_id}/mismatches")
    assert response.status_code == 200
    body = response.json()

    assert body["rows"]["items"] == []
    assert body["rows"]["total"] == 0
    assert body["tallies"] == []
    #: The filter options still arrive, so a client can render the toolbar.
    assert body["runs"] != []
    assert body["descriptor"]["evaluation_id"] == unscored.evaluation_id


async def test_an_unknown_evaluation_is_404(api_client: AsyncClient) -> None:
    """*That* is genuinely absent, and 404 is the honest answer for it — the
    distinction the empty list above turns on."""
    response = await api_client.get("/api/v1/evaluations/no-such-eval/mismatches")
    assert response.status_code == 404


async def test_the_list_is_scoped_to_one_run(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """`SD26`, §17.6 — `run` selects rather than filters, and there is no "all
    runs" value to pass."""
    first = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
    )
    second = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={"run": scored.run_ids[1], "page_size": 100},
    )

    assert first.json()["filters"]["run_id"] == scored.run_ids[0]
    assert second.json()["filters"]["run_id"] == scored.run_ids[1]
    assert second.json()["run_label"].startswith("run 2 · ")
    ids = {row["mismatch_id"] for row in first.json()["rows"]["items"]}
    assert ids & {row["mismatch_id"] for row in second.json()["rows"]["items"]} == set()


async def test_the_filters_are_echoed_back(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """A client renders the toolbar from the response rather than from what it
    believes it asked for — which is what keeps a deep link and the controls in
    agreement."""
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={"feature": scored.feature_ids[WEATHER], "tag_state": "untagged"},
    )
    assert response.status_code == 200
    filters = response.json()["filters"]

    assert filters["feature_id"] == scored.feature_ids[WEATHER]
    assert filters["tag_state"] == "untagged"


@pytest.mark.parametrize("tag_state", ["any", "untagged", "tagged", "hallucination", "unclear"])
async def test_every_tag_filter_value_is_accepted(
    api_client: AsyncClient, scored: ScoredCorpus, tag_state: str
) -> None:
    """The closed vocabulary, on the wire: three states plus the three named
    tags, and the two enums' values are disjoint so the union discriminates
    itself (§17.5)."""
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={"tag_state": tag_state},
    )
    assert response.status_code == 200


async def test_an_unknown_tag_filter_is_422(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """The filter vocabulary is closed too. A fourth stored tag is visible in
    the list and counted under `other`; it is simply not offered as a filter
    until somebody adds it, and asking for one is a 422 rather than a silently
    empty page."""
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={"tag_state": "fourth_thing"},
    )
    assert response.status_code == 422


async def test_paging_is_bounded_and_reported(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={"page": 1, "page_size": 2, "sort_key": "record", "sort_dir": "desc"},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]

    assert len(rows["items"]) == 2
    assert rows["page"] == 1
    assert rows["page_size"] == 2
    assert rows["sort_key"] == "record"
    assert rows["sort_dir"] == "desc"
    assert rows["total"] > 2

    assert (
        await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page": 0}
        )
    ).status_code == 422
    assert (
        await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 5000}
        )
    ).status_code == 422


# --- the write --------------------------------------------------------------


async def test_tagging_writes_the_tag_and_stamps_it(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    row = await _first_mismatch(api_client, scored)

    response = await api_client.post(
        f"/api/v1/mismatches/{row['mismatch_id']}/tag",
        json={"tag": "structured_data_error", "note": "record is wrong"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["analyst_tag"] == "structured_data_error"
    assert body["tag"] == "structured_data_error"
    assert body["is_other"] is False
    assert body["reviewed"] is True
    assert body["tagged_at"] is not None
    assert body["note"] == "record is wrong"


async def test_tagging_is_idempotent(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """The same tag twice leaves **one row and one `tagged_at`**.

    A retried request — a double click, a flaky connection — must not produce a
    second row in the one table a human writes to.
    """
    row = await _first_mismatch(api_client, scored)
    url = f"/api/v1/mismatches/{row['mismatch_id']}/tag"
    before = (
        await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
        )
    ).json()["rows"]["total"]

    first = await api_client.post(url, json={"tag": "unclear"})
    second = await api_client.post(url, json={"tag": "unclear"})

    assert first.status_code == second.status_code == 200
    assert first.json()["tagged_at"] == second.json()["tagged_at"]
    after = (
        await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
        )
    ).json()["rows"]
    assert after["total"] == before
    assert sum(1 for r in after["items"] if r["reviewed"]) == 1


async def test_an_unknown_tag_value_is_422_and_never_reaches_the_column(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """**`SD24` on the wire** (§17.5).

    `analyst_tag` stays `String(32)` so a fourth tag needs no migration —
    that is a schema decision. This is the other half: nothing in the MVP may
    *write* one, so the request model takes a `MismatchTag` and FastAPI answers
    before the service is reached. A closed enum over an open column is wrong
    in both directions if only half of it lands.
    """
    row = await _first_mismatch(api_client, scored)
    url = f"/api/v1/mismatches/{row['mismatch_id']}/tag"

    assert (await api_client.post(url, json={"tag": "fourth_thing"})).status_code == 422
    assert (await api_client.post(url, json={"tag": "other"})).status_code == 422
    assert (await api_client.post(url, json={"tag": ""})).status_code == 422
    assert (await api_client.post(url, json={})).status_code == 422

    after = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
    )
    assert all(r["analyst_tag"] is None for r in after.json()["rows"]["items"])


async def test_tagging_an_unknown_mismatch_is_404(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.post(
        "/api/v1/mismatches/no-such-mismatch/tag", json={"tag": "unclear"}
    )
    assert response.status_code == 404


async def test_clearing_returns_the_cleared_row(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """A body rather than a bare 204: the cleared row is what the screen
    redraws, so it does not have to re-read to find out."""
    row = await _first_mismatch(api_client, scored)
    url = f"/api/v1/mismatches/{row['mismatch_id']}/tag"
    await api_client.post(url, json={"tag": "hallucination", "note": "invented"})

    response = await api_client.delete(url)
    assert response.status_code == 200
    body = response.json()

    assert body["analyst_tag"] is None
    assert body["tag"] is None
    assert body["tagged_at"] is None
    assert body["note"] is None
    assert body["reviewed"] is False
    #: The scorer's half is untouched by either write (§17.1).
    assert body["evidence_span"] == row["evidence_span"]
    assert body["record_value"] == row["record_value"]


async def test_clearing_an_unknown_mismatch_is_404(api_client: AsyncClient) -> None:
    assert (await api_client.delete("/api/v1/mismatches/nope/tag")).status_code == 404


# --- the tally --------------------------------------------------------------


async def test_the_tally_carries_all_three_buckets_and_the_other_one(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """`counts` always has all three keys, so a client cannot have to guess
    whether a missing one means "none" or "not counted"."""
    row = await _first_mismatch(api_client, scored)
    await api_client.post(f"/api/v1/mismatches/{row['mismatch_id']}/tag", json={"tag": "unclear"})

    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/mismatches/tally")
    assert response.status_code == 200
    entries = response.json()

    assert entries
    for entry in entries:
        assert set(entry["counts"]) == {"hallucination", "structured_data_error", "unclear"}
        assert entry["other"] == 0
        assert entry["reviewed"] + entry["untagged"] == entry["total"]
    assert sum(e["counts"]["unclear"] for e in entries) == 1


async def test_the_tally_endpoint_agrees_with_the_list_endpoint(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """Two endpoints, one read (§17.4). If they could disagree, a client would
    have two numbers on one screen and no way to tell which is the lie."""
    listed = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 100}
    )
    tallied = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/mismatches/tally")

    assert listed.json()["tallies"] == tallied.json()
    assert sum(e["total"] for e in tallied.json()) == listed.json()["rows"]["total"]


async def test_the_tally_is_scoped_to_the_same_filter_as_the_list(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    params = {"feature": scored.feature_ids[WEATHER]}
    listed = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches",
        params={**params, "page_size": 100},
    )
    tallied = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches/tally", params=params
    )

    assert [e["feature_key"] for e in tallied.json()] == [WEATHER]
    assert tallied.json()[0]["total"] == listed.json()["rows"]["total"]


async def test_an_unknown_evaluation_tally_is_404(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/evaluations/nope/mismatches/tally")).status_code == 404


# --- the export -------------------------------------------------------------


async def test_the_csv_streams_with_the_bom(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """N3. Excel on Windows cannot read UTF-8 without it, and the charset is
    declared rather than left for a browser to guess."""
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/mismatches.csv")
    assert response.status_code == 200

    assert response.content.startswith(CSV_BOM)
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    assert f"mismatches-{scored.evaluation_id}.csv" in response.headers["content-disposition"]


async def test_the_csv_carries_the_review_and_honours_the_filter(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """`C6`/`P4-D3`: an export whose point is review has to carry the review,
    and it writes the **currently filtered** table rather than the whole run."""
    row = await _first_mismatch(api_client, scored)
    await api_client.post(
        f"/api/v1/mismatches/{row['mismatch_id']}/tag",
        json={"tag": "hallucination", "note": "invented"},
    )

    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches.csv",
        params={"tag_state": "hallucination"},
    )
    lines = response.content.decode("utf-8-sig").splitlines()

    assert lines[0] == CLASSIFICATION_COMMENT
    assert lines[1].startswith("# evaluation ")
    assert "tag hallucination" in lines[1]
    assert "1 mismatches, 1 reviewed" in lines[1]
    assert lines[2].startswith("mismatch_id;record_id;anonymised;feature_key")
    assert len(lines) == 4, "classification, comment, header, and the one filtered row"
    assert "invented" in lines[3]


async def test_the_csv_of_an_unknown_evaluation_is_404(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/evaluations/nope/mismatches.csv")).status_code == 404


async def test_the_csv_is_unpaged(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    """An export has no paging of its own (sw-design.md §7): `page_size` is not
    even a parameter here, and the file holds the whole filtered set."""
    listed = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/mismatches", params={"page_size": 1}
    )
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/mismatches.csv")
    lines = response.content.decode("utf-8-sig").splitlines()

    assert len(listed.json()["rows"]["items"]) == 1
    # classification line, evaluation comment, header row (risk B1 added the
    # first of the three).
    assert len(lines) == listed.json()["rows"]["total"] + 3
