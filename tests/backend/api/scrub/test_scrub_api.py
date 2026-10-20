"""`/api/v1/scrub` and the freeze's scrub fields, through `httpx.ASGITransport`
(sw-design.md §19.7).

The service's own behaviour is asserted in `tests/backend/services/scrub/`;
this is the wire: status codes, the 422 body's top-level codes, and that a
freeze over HTTP stores scrubbed text and says which rules it used.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.backend

HazardBytes = Callable[[str, str], bytes]

_SCRUB = Path(__file__).resolve().parents[3] / "fixtures" / "scrub" / "hazards"


def _fixture(name: str) -> bytes:
    return (_SCRUB / name).read_bytes()


async def _import(client: httpx.AsyncClient, kind: str, name: str) -> httpx.Response:
    return await client.post(
        f"/api/v1/scrub/lists/{kind}", files={"file": (name, _fixture(name), "text/plain")}
    )


async def _import_all(client: httpx.AsyncClient) -> None:
    for kind, name in (
        ("regex", "s04_rules.toml"),
        ("firstname", "s01_firstnames.txt"),
        ("lastname", "s02_lastnames.txt"),
        ("whitelist", "s03_whitelist.txt"),
    ):
        response = await _import(client, kind, name)
        assert response.status_code == 200, response.text


async def _h18_delivery(client: httpx.AsyncClient, hazard_bytes: HazardBytes) -> str:
    registered = await client.post(
        "/api/v1/deliveries", json={"name": "h18", "source_kind": "upload"}
    )
    delivery_id: str = registered.json()["delivery_id"]
    for filename in ("unfall.txt", "text.csv"):
        await client.post(
            f"/api/v1/deliveries/{delivery_id}/files",
            files={
                "file": (filename, hazard_bytes("h18_names_in_narrative", filename), "text/plain")
            },
        )
    await client.post(f"/api/v1/deliveries/{delivery_id}/analyse")
    return delivery_id


async def test_the_active_set_is_the_mandatory_rules_before_any_import(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.get("/api/v1/scrub/active")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] is None
    assert [r["rule_id"] for r in body["rules"]] == ["license-plate", "phone", "email"]


async def test_an_import_makes_a_version_and_says_what_it_counted(
    api_client: httpx.AsyncClient,
) -> None:
    response = await _import(api_client, "lastname", "s02_lastnames.txt")
    assert response.status_code == 200
    body = response.json()
    assert (body["no_change"], body["ruleset"]["version"]) == (False, 1)
    assert {"bom", "duplicates", "too_short"} <= {n["code"] for n in body["notices"]}
    again = await _import(api_client, "lastname", "s02_lastnames.txt")
    assert again.json()["no_change"] is True


async def test_a_refused_import_is_422_with_its_codes_at_the_top_level(
    api_client: httpx.AsyncClient,
) -> None:
    response = await _import(api_client, "regex", "s06_slow_rule.toml")
    assert response.status_code == 422
    assert response.json() == {
        "import_errors": [{"code": "pattern_too_slow", "rule_id": "slow", "detail": {}}]
    }
    assert (await api_client.get("/api/v1/scrub/versions")).json() == []


async def test_an_unknown_kind_is_a_validation_error(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/scrub/lists/nicknames", files={"file": ("n.txt", b"Hansi\n", "text/plain")}
    )
    assert response.status_code == 422
    assert "import_errors" not in response.json()


async def test_removing_a_list_makes_a_version_without_it(api_client: httpx.AsyncClient) -> None:
    await _import(api_client, "whitelist", "s03_whitelist.txt")
    response = await api_client.delete("/api/v1/scrub/lists/whitelist")
    assert response.status_code == 200
    assert (response.json()["ruleset"]["version"], response.json()["ruleset"]["lists"]) == (2, [])


async def test_entries_are_searched_and_paged(api_client: httpx.AsyncClient) -> None:
    await _import(api_client, "lastname", "s02_lastnames.txt")
    response = await api_client.get(
        "/api/v1/scrub/lists/lastname/entries", params={"query": "MUELL", "page_size": 5}
    )
    assert response.status_code == 200
    body = response.json()
    assert [e["entry"] for e in body["items"]] == ["Müller"]
    assert body["meta"]["total"] == 1


async def test_a_sentence_is_scrubbed_and_answered(api_client: httpx.AsyncClient) -> None:
    await _import_all(api_client)
    response = await api_client.post(
        "/api/v1/scrub/try", json={"text": "Herr Meier, 079 123 45 67"}
    )
    assert response.status_code == 200
    assert response.json()["text"] == "Herr <Lastname_1>, <Phone_1>"


async def test_the_dry_run_and_the_freeze_agree_over_http(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    await _import_all(api_client)
    delivery_id = await _h18_delivery(api_client, hazard_bytes)
    preview = await api_client.get("/api/v1/scrub/preview", params={"delivery_id": delivery_id})
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    # The examples are personal data for the dialog alone (SD70).
    assert "examples" not in shown

    created = await api_client.post(
        "/api/v1/corpora",
        json={"delivery_id": delivery_id, "name": "h18", "scrub_ruleset_id": shown["ruleset_id"]},
    )
    assert created.status_code == 201, created.text
    corpus = created.json()
    assert (corpus["scrubbed"], corpus["scrub_version"]) == (True, 4)
    assert corpus["scrub_counts"] == shown["counts"]


async def test_a_freeze_naming_an_unknown_version_is_404(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    delivery_id = await _h18_delivery(api_client, hazard_bytes)
    created = await api_client.post(
        "/api/v1/corpora",
        json={"delivery_id": delivery_id, "name": "h18", "scrub_ruleset_id": "no-such-version"},
    )
    assert created.status_code == 404


async def test_the_dry_run_of_an_unknown_delivery_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/scrub/preview", params={"delivery_id": "nope"})
    assert response.status_code == 404
