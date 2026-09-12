"""`/api/v1/codelists` through `httpx.ASGITransport` — no network (F1, Wave 3).

The two contracts that matter at this layer (sw-design.md §14.1, plan-phase-2.md §9):
- a malformed upload returns **422 with the validation errors** and writes nothing;
- a re-upload of the exact same file returns **200 with `no_change: true`**.

Everything else is thin-router plumbing; `CodelistService`'s own behaviour
(import, coverage, mapping) is E1's, asserted in `tests/backend/services/codelist/**`.

`hazard_bytes`/`hazards_dir` come from `tests/backend/api/conftest.py` (C1) —
a legitimate ancestor conftest of this directory, reused read-only exactly as
`tests/backend/api/census/conftest.py` (C2) reuses `tests/backend/conftest.py`'s
fixtures rather than inventing a fourth way to read a hazard file.
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from tests.conftest import FrozenClock

pytestmark = pytest.mark.backend

HazardBytes = Callable[[str, str], bytes]

#: `tests/backend/api/codelists/` -> `tests/`
_TESTS_ROOT = Path(__file__).resolve().parents[3]
_MALFORMED_CODELIST = (
    _TESTS_ROOT / "fixtures" / "codelists" / "hazards" / "c04_missing_codes_key" / "codelist.json"
)

#: A single-attribute, single-code codelist matching `HauptUrsaAusw`'s real
#: value ("1") in the `h10_count_mismatch` delivery fixture (`tests/fixtures/
#: deliveries/hazards/h10_count_mismatch/unfall.txt`) — enough to exercise a
#: clean `ok` coverage round-trip without needing a second hazard fixture.
_MAIN_CAUSE_CODELIST = json.dumps(
    {
        "main_cause": {
            "chapter": "4.1.4",
            "name": {"de": "Hauptursache", "fr": "Cause principale", "it": "Causa principale"},
            "codes": {
                "1": {
                    "de": "Missachten Vortrittsrecht",
                    "fr": "Non-respect de la priorité",
                    "it": "Precedenza non rispettata",
                }
            },
        }
    }
).encode("utf-8")

#: A second, distinct generation — same shape, different content/hash, so
#: "no_change" tests have a real second file to *not* be confused with.
_ROAD_TYPE_CODELIST = json.dumps(
    {
        "road_type": {
            "name": {"de": "Strassenart", "fr": "Type de route", "it": "Tipo di strada"},
            "codes": {"01": {"de": "Autobahn", "fr": "Autoroute", "it": "Autostrada"}},
        }
    }
).encode("utf-8")


async def _import_codelist(api_client: httpx.AsyncClient, content: bytes) -> httpx.Response:
    return await api_client.post(
        "/api/v1/codelists/import",
        files={"file": ("codelist.json", content, "application/json")},
    )


async def _upload_and_analyse(
    api_client: httpx.AsyncClient, hazard: str, filenames: list[str], hazard_bytes: HazardBytes
) -> str:
    """Same idiom as `tests/backend/api/corpora/test_corpora_api.py` (C1):
    register a delivery, upload its files, analyse. Duplicated here rather
    than imported, since `tests/backend/api/corpora/**` is C1's own path."""
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": hazard, "source_kind": "upload"}
    )
    delivery_id: str = registered.json()["delivery_id"]
    for filename in filenames:
        await api_client.post(
            f"/api/v1/deliveries/{delivery_id}/files",
            files={"file": (filename, hazard_bytes(hazard, filename), "text/plain")},
        )
    await api_client.post(f"/api/v1/deliveries/{delivery_id}/analyse")
    return delivery_id


async def _seed_corpus(api_client: httpx.AsyncClient, hazard_bytes: HazardBytes, name: str) -> str:
    delivery_id = await _upload_and_analyse(
        api_client, "h10_count_mismatch", ["unfall.txt", "objekt.txt", "person.txt"], hazard_bytes
    )
    created = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": delivery_id, "name": name}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["corpus_id"])


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


async def test_import_codelist_writes_a_new_generation(api_client: httpx.AsyncClient) -> None:
    response = await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)

    assert response.status_code == 200
    body = response.json()
    assert body["attribute_count"] == 1
    assert body["no_change"] is False
    assert body["code_table_import_id"]
    assert len(body["source_hash"]) == 64  # sha256 hex digest
    assert body["imported_at"]


async def test_reimporting_the_exact_same_file_is_a_no_op(api_client: httpx.AsyncClient) -> None:
    first = await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)
    assert first.status_code == 200
    first_body = first.json()

    second = await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)
    assert second.status_code == 200
    second_body = second.json()

    assert second_body["no_change"] is True
    assert second_body["code_table_import_id"] == first_body["code_table_import_id"]
    assert second_body["source_hash"] == first_body["source_hash"]


async def test_reimporting_a_different_file_is_a_new_generation(
    api_client: httpx.AsyncClient,
) -> None:
    first = await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)
    second = await _import_codelist(api_client, _ROAD_TYPE_CODELIST)

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["no_change"] is False
    assert second_body["code_table_import_id"] != first.json()["code_table_import_id"]


async def test_import_malformed_codelist_returns_422_with_validation_errors(
    api_client: httpx.AsyncClient,
) -> None:
    """D1's `c04_missing_codes_key` hazard: one attribute ("weather") has no
    `codes` key at all — a structural error, not a 500 (Do-NOT list #6)."""
    response = await _import_codelist(api_client, _MALFORMED_CODELIST.read_bytes())

    assert response.status_code == 422
    body = response.json()
    assert body["import_errors"], "expected the structural validation errors in the body"
    assert any(e["attribute_key"] == "weather" for e in body["import_errors"])
    for error in body["import_errors"]:
        assert error["path"]
        assert error["message"]


async def test_import_malformed_codelist_writes_nothing(api_client: httpx.AsyncClient) -> None:
    response = await _import_codelist(api_client, _MALFORMED_CODELIST.read_bytes())
    assert response.status_code == 422

    attributes = await api_client.get("/api/v1/codelists/attributes")
    assert attributes.json() == []


# ---------------------------------------------------------------------------
# attributes
# ---------------------------------------------------------------------------


async def test_list_attributes_returns_the_latest_import_only(
    api_client: httpx.AsyncClient, frozen_clock: FrozenClock
) -> None:
    await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)
    # `get_latest_import()` orders by `imported_at` (codelist_repo.py) — the
    # clock must actually move between two generations for "latest" to be
    # unambiguous, exactly as a real re-upload some time later would.
    frozen_clock.advance(seconds=1)
    await _import_codelist(api_client, _ROAD_TYPE_CODELIST)

    response = await api_client.get("/api/v1/codelists/attributes")

    assert response.status_code == 200
    body = response.json()
    assert [a["key"] for a in body] == ["road_type"]
    assert body[0]["code_count"] == 1
    assert body[0]["name"] == {"de": "Strassenart", "fr": "Type de route", "it": "Tipo di strada"}


async def test_list_attributes_starts_empty(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/codelists/attributes")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# columns, mapping, coverage — the full round trip
# ---------------------------------------------------------------------------


async def test_columns_mapping_and_coverage_round_trip(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    corpus_id = await _seed_corpus(api_client, hazard_bytes, "codelist round trip")

    imported = await _import_codelist(api_client, _MAIN_CAUSE_CODELIST)
    assert imported.status_code == 200

    attributes = (await api_client.get("/api/v1/codelists/attributes")).json()
    code_attribute_id = next(a["code_attribute_id"] for a in attributes if a["key"] == "main_cause")

    # -- before mapping: the enum column is listed, unmapped ----------------
    before = await api_client.get(
        "/api/v1/codelists/columns", params={"corpus_id": corpus_id, "language": "de"}
    )
    assert before.status_code == 200
    columns_by_name = {c["column_name"]: c for c in before.json()}
    assert "HauptUrsaAusw" in columns_by_name, "an *Ausw column must be listed as an enum column"
    target = columns_by_name["HauptUrsaAusw"]
    assert target["table_name"] == "unfall"
    assert target["mapping_id"] is None
    assert target["mapped_attribute"] is None
    assert target["coverage"] is None

    # -- map it ---------------------------------------------------------------
    mapped = await api_client.put(
        "/api/v1/codelists/columns/mapping",
        json={
            "corpus_id": corpus_id,
            "source_column": "HauptUrsaAusw",
            "code_attribute_id": code_attribute_id,
        },
    )
    assert mapped.status_code == 200
    mapped_body = mapped.json()
    assert mapped_body["mapping_id"] is not None
    assert mapped_body["mapped_attribute"]["key"] == "main_cause"
    assert mapped_body["coverage"] is not None
    assert mapped_body["coverage"]["status"] == "ok"
    assert mapped_body["coverage"]["language"] == "de"
    assert mapped_body["coverage"]["total_count"] == 1
    assert mapped_body["coverage"]["labelled_count"] == 1
    usage = mapped_body["coverage"]["codes"][0]
    assert usage["code"] == "1"
    assert usage["count"] == 1
    assert usage["share"] == pytest.approx(1.0)
    assert usage["label"] == "Missachten Vortrittsrecht"
    assert usage["in_codelist"] is True

    # -- read it back ---------------------------------------------------------
    after = await api_client.get(
        "/api/v1/codelists/columns", params={"corpus_id": corpus_id, "language": "de"}
    )
    after_target = next(c for c in after.json() if c["column_name"] == "HauptUrsaAusw")
    assert after_target["mapping_id"] == mapped_body["mapping_id"]
    assert after_target["mapped_attribute"]["key"] == "main_cause"
    assert after_target["coverage"]["status"] == "ok"

    # -- unmap it ---------------------------------------------------------------
    unmapped = await api_client.delete(
        "/api/v1/codelists/columns/mapping",
        params={"corpus_id": corpus_id, "source_column": "HauptUrsaAusw"},
    )
    assert unmapped.status_code == 204
    assert unmapped.content == b""

    final = await api_client.get(
        "/api/v1/codelists/columns", params={"corpus_id": corpus_id, "language": "de"}
    )
    final_target = next(c for c in final.json() if c["column_name"] == "HauptUrsaAusw")
    assert final_target["mapping_id"] is None
    assert final_target["mapped_attribute"] is None
    assert final_target["coverage"] is None


async def test_unmap_column_that_is_not_mapped_is_a_no_op(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    corpus_id = await _seed_corpus(api_client, hazard_bytes, "no-op unmap")

    response = await api_client.delete(
        "/api/v1/codelists/columns/mapping",
        params={"corpus_id": corpus_id, "source_column": "HauptUrsaAusw"},
    )
    assert response.status_code == 204


async def test_map_column_with_an_unknown_code_attribute_id_is_404(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    corpus_id = await _seed_corpus(api_client, hazard_bytes, "unknown attribute")

    response = await api_client.put(
        "/api/v1/codelists/columns/mapping",
        json={
            "corpus_id": corpus_id,
            "source_column": "HauptUrsaAusw",
            "code_attribute_id": "no-such-attribute",
        },
    )

    assert response.status_code == 404


async def test_list_columns_only_lists_enum_columns(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    """`AnzObjFeld` is a `Feld`-suffixed numeric column, never enum-typed —
    it must never appear in the Codelists master list (mvp-spec.md §7)."""
    corpus_id = await _seed_corpus(api_client, hazard_bytes, "enum only")

    response = await api_client.get(
        "/api/v1/codelists/columns", params={"corpus_id": corpus_id, "language": "de"}
    )

    assert response.status_code == 200
    names = {c["column_name"] for c in response.json()}
    assert "AnzObjFeld" not in names
    assert all(name.endswith("Ausw") for name in names)
