"""`/api/v1/feature-configs` through `httpx.ASGITransport` — no network (F2).

Thin-router plumbing over `FeatureService` (E2, Wave 2): every conversion
between the wire schemas (`ra2/api/schemas.py`) and the domain types
(`ra2/domain/feature.py`) lives in `ra2/api/v1/features.py`, and the
derivation round-trip tests below are the proof it is lossless.
`FeatureService`'s own behaviour (validation tiers, ordinal management,
fingerprinting) is E2's, asserted in `tests/backend/services/feature/**` —
not re-asserted here beyond what the wire layer must preserve.

`api_client` and friends come from `tests/backend/api/conftest.py` (shared
across every `tests/backend/api/**` suite); no feature-specific fixtures are
needed since `create_draft` takes no corpus and no uploaded file.
"""

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.backend


def _feature_body(**overrides: object) -> dict[str, object]:
    """A minimal valid labelled feature: accident grain, enum, exact match —
    the same defaults `tests/backend/services/feature/conftest.py` uses, so
    the hazard under test is visible in the one field a test overrides."""
    body: dict[str, object] = {
        "key": "weather",
        "kind": "labelled",
        "description": "The weather at the time of the accident.",
        "grain": "accident",
        "source_column": "WitterungAusw",
        "value_type": "enum",
        "matching_rule": {"kind": "exact"},
    }
    body.update(overrides)
    return body


async def _create_draft(
    api_client: httpx.AsyncClient, name: str = "Weather & conditions"
) -> dict[str, Any]:
    response = await api_client.post("/api/v1/feature-configs", json={"name": name})
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


async def _add_feature(
    api_client: httpx.AsyncClient, feature_config_id: str, **overrides: object
) -> httpx.Response:
    return await api_client.post(
        f"/api/v1/feature-configs/{feature_config_id}/features", json=_feature_body(**overrides)
    )


# ---------------------------------------------------------------------------
# list / create / get / delete config
# ---------------------------------------------------------------------------


async def test_list_feature_configs_starts_empty(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/feature-configs")
    assert response.status_code == 200
    assert response.json() == []


async def test_create_feature_config_creates_an_empty_draft(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/feature-configs", json={"name": "Weather & conditions", "description": "v1"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Weather & conditions"
    assert body["description"] == "v1"
    assert body["version"] == 1
    assert body["frozen_at"] is None
    assert body["locked_by_evaluations"] == 0
    assert body["features"] == []

    listed = await api_client.get("/api/v1/feature-configs")
    assert [c["feature_config_id"] for c in listed.json()] == [body["feature_config_id"]]
    assert listed.json()[0]["feature_count"] == 0


async def test_get_feature_config_returns_it(api_client: httpx.AsyncClient) -> None:
    created = await _create_draft(api_client)

    response = await api_client.get(f"/api/v1/feature-configs/{created['feature_config_id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_unknown_feature_config_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/feature-configs/no-such-config")
    assert response.status_code == 404


async def test_delete_feature_config_removes_it(api_client: httpx.AsyncClient) -> None:
    created = await _create_draft(api_client)

    response = await api_client.delete(f"/api/v1/feature-configs/{created['feature_config_id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (
        await api_client.get(f"/api/v1/feature-configs/{created['feature_config_id']}")
    ).status_code == 404


async def test_delete_unknown_feature_config_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.delete("/api/v1/feature-configs/no-such-config")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# add / edit / delete feature
# ---------------------------------------------------------------------------


async def test_add_feature_returns_the_whole_updated_set(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)

    response = await _add_feature(api_client, draft["feature_config_id"], key="weather")

    assert response.status_code == 200
    body = response.json()
    assert [f["key"] for f in body["features"]] == ["weather"]
    only = body["features"][0]
    assert only["feature_config_id"] == draft["feature_config_id"]
    assert only["ordinal"] == 0
    assert only["kind"] == "labelled"
    assert only["grain"] == "accident"
    assert only["value_type"] == "enum"
    assert only["source_column"] == "WitterungAusw"
    assert only["derivation"] is None
    assert only["matching_rule"] == {
        "kind": "exact",
        "tolerance_minutes": None,
        "decimal_precision": None,
    }
    assert only["fingerprint"] is None
    assert len(only["fingerprint_preview"]) == 64
    assert only["validation_errors"] == []


@pytest.mark.parametrize(
    ("kind", "grain", "value_type", "extra"),
    [
        ("labelled", "accident", "enum", {"source_column": "WitterungAusw"}),
        ("labelled", "accident", "integer", {"source_column": "HoechstGeschwKmHFeld"}),
        (
            "exploratory",
            "accident",
            "free_text",
            {"source_column": None, "matching_rule": {"kind": "none"}},
        ),
    ],
    ids=["enum", "integer", "exploratory"],
)
async def test_add_feature_of_each_kind_grain_value_type(
    api_client: httpx.AsyncClient,
    kind: str,
    grain: str,
    value_type: str,
    extra: dict[str, object],
) -> None:
    draft = await _create_draft(api_client)

    response = await _add_feature(
        api_client,
        draft["feature_config_id"],
        key=f"{kind}_{value_type}",
        kind=kind,
        grain=grain,
        value_type=value_type,
        **extra,
    )

    assert response.status_code == 200
    only = response.json()["features"][0]
    assert only["kind"] == kind
    assert only["grain"] == grain
    assert only["value_type"] == value_type


#: One payload per derivation type (mvp-spec.md §8.3's closed catalogue),
#: written out with every `DerivationSpecSchema` field present — the wire
#: shape a round trip actually returns — so the equality check below is
#: exact, not "the fields I remembered to check".
DERIVATION_PAYLOADS = [
    pytest.param(
        {
            "type": "count_objects",
            "filter": None,
            "table": None,
            "column": None,
            "ordered_codes": None,
        },
        id="count_objects_no_filter",
    ),
    pytest.param(
        {
            "type": "count_objects",
            "filter": {"column": "FahrzeugartAusw", "operator": "eq", "value": "M12"},
            "table": None,
            "column": None,
            "ordered_codes": None,
        },
        id="count_objects_with_filter",
    ),
    pytest.param(
        {
            "type": "count_persons",
            "filter": {"column": "VerletzungsgradAusw", "operator": "is_not_empty", "value": None},
            "table": None,
            "column": None,
            "ordered_codes": None,
        },
        id="count_persons",
    ),
    pytest.param(
        {
            "type": "any_object_matches",
            "filter": {"column": "FahrzeugartAusw", "operator": "in", "value": ["M12", "M13"]},
            "table": None,
            "column": None,
            "ordered_codes": None,
        },
        id="any_object_matches",
    ),
    pytest.param(
        {
            "type": "any_person_matches",
            "filter": {"column": "GeschlechtAusw", "operator": "not_in", "value": ["1", "2"]},
            "table": None,
            "column": None,
            "ordered_codes": None,
        },
        id="any_person_matches",
    ),
    pytest.param(
        {
            "type": "max_ordinal",
            "filter": None,
            "table": "person",
            "column": "VerletzungsgradAusw",
            "ordered_codes": ["1", "2", "3", "4"],
        },
        id="max_ordinal",
    ),
    pytest.param(
        {
            "type": "min_ordinal",
            "filter": None,
            "table": "objekt",
            "column": "SchadenAusw",
            "ordered_codes": ["A", "B"],
        },
        id="min_ordinal",
    ),
    pytest.param(
        {
            "type": "distinct_count",
            "filter": None,
            "table": "objekt",
            "column": "FahrzeugartAusw",
            "ordered_codes": None,
        },
        id="distinct_count",
    ),
]


@pytest.mark.parametrize("derivation", DERIVATION_PAYLOADS)
async def test_every_derivation_round_trips_through_the_api(
    api_client: httpx.AsyncClient, derivation: dict[str, object]
) -> None:
    draft = await _create_draft(api_client)

    added = await _add_feature(
        api_client,
        draft["feature_config_id"],
        key="derived_thing",
        grain="derived",
        source_column=None,
        value_type="integer",
        derivation=derivation,
    )

    assert added.status_code == 200
    assert added.json()["features"][0]["derivation"] == derivation

    fetched = await api_client.get(f"/api/v1/feature-configs/{draft['feature_config_id']}")
    assert fetched.json()["features"][0]["derivation"] == derivation


async def test_edit_feature_replaces_every_field(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)
    added = await _add_feature(api_client, draft["feature_config_id"], key="weather")
    feature_id = added.json()["features"][0]["feature_id"]

    response = await api_client.put(
        f"/api/v1/feature-configs/{draft['feature_config_id']}/features/{feature_id}",
        json=_feature_body(
            key="accident_time",
            description="The time on the clock when it happened.",
            source_column="UnfallZeitFeld",
            value_type="time",
            matching_rule={"kind": "within_tolerance", "tolerance_minutes": 15},
        ),
    )

    assert response.status_code == 200
    only = response.json()["features"][0]
    assert only["feature_id"] == feature_id
    assert only["key"] == "accident_time"
    assert only["source_column"] == "UnfallZeitFeld"
    assert only["value_type"] == "time"
    assert only["matching_rule"] == {
        "kind": "within_tolerance",
        "tolerance_minutes": 15,
        "decimal_precision": None,
    }


async def test_edit_of_an_unknown_feature_is_404(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)

    response = await api_client.put(
        f"/api/v1/feature-configs/{draft['feature_config_id']}/features/no-such-feature",
        json=_feature_body(),
    )

    assert response.status_code == 404


async def test_delete_feature_removes_it(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)
    added = await _add_feature(api_client, draft["feature_config_id"], key="weather")
    feature_id = added.json()["features"][0]["feature_id"]

    response = await api_client.delete(
        f"/api/v1/feature-configs/{draft['feature_config_id']}/features/{feature_id}"
    )

    assert response.status_code == 204
    assert response.content == b""
    fetched = await api_client.get(f"/api/v1/feature-configs/{draft['feature_config_id']}")
    assert fetched.json()["features"] == []


async def test_delete_unknown_feature_is_404(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)

    response = await api_client.delete(
        f"/api/v1/feature-configs/{draft['feature_config_id']}/features/no-such-feature"
    )

    assert response.status_code == 404


async def test_add_feature_with_a_malformed_kind_is_422(api_client: httpx.AsyncClient) -> None:
    """The frozen `FeatureRequest.kind` is a bare `str`; the route is what
    enforces membership in `ra2.domain.feature.Kind` (a judgment call, see
    the F2 report: without this the same input would 500)."""
    draft = await _create_draft(api_client)

    response = await _add_feature(api_client, draft["feature_config_id"], kind="not-a-kind")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------


async def test_freeze_stamps_frozen_at_and_every_fingerprint(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)
    await _add_feature(api_client, draft["feature_config_id"], key="weather", value_type="integer")

    response = await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")

    assert response.status_code == 200
    body = response.json()
    assert body["frozen_at"] is not None
    assert all(f["fingerprint"] is not None for f in body["features"])


async def test_freeze_blocking_returns_422_with_validation_errors_and_creates_nothing(
    api_client: httpx.AsyncClient,
) -> None:
    """mvp-spec.md §8.2: a labelled feature scored at object grain blocks."""
    draft = await _create_draft(api_client)
    await _add_feature(
        api_client,
        draft["feature_config_id"],
        key="damage_per_vehicle",
        grain="object",
        source_column="SchadenAusw",
    )

    response = await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")

    assert response.status_code == 422
    body = response.json()
    assert body["validation_errors"]
    assert "damage_per_vehicle" in body["validation_errors"][0]

    fetched = await api_client.get(f"/api/v1/feature-configs/{draft['feature_config_id']}")
    assert fetched.json()["frozen_at"] is None


async def test_freeze_of_an_unknown_config_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post("/api/v1/feature-configs/no-such-config/freeze")
    assert response.status_code == 404


async def test_freeze_of_an_already_frozen_config_is_409(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)
    await _add_feature(api_client, draft["feature_config_id"], value_type="integer")
    await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")

    response = await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# a frozen config refuses every edit endpoint
# ---------------------------------------------------------------------------


async def test_frozen_config_edit_endpoints_are_409(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)
    added = await _add_feature(
        api_client, draft["feature_config_id"], key="weather", value_type="integer"
    )
    feature_id = added.json()["features"][0]["feature_id"]
    await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")
    config_id = draft["feature_config_id"]

    assert (
        await _add_feature(api_client, config_id, key="light", value_type="integer")
    ).status_code == 409
    assert (
        await api_client.put(
            f"/api/v1/feature-configs/{config_id}/features/{feature_id}",
            json=_feature_body(value_type="integer"),
        )
    ).status_code == 409
    assert (
        await api_client.delete(f"/api/v1/feature-configs/{config_id}/features/{feature_id}")
    ).status_code == 409
    assert (await api_client.delete(f"/api/v1/feature-configs/{config_id}")).status_code == 409


# ---------------------------------------------------------------------------
# clone
# ---------------------------------------------------------------------------


async def test_clone_of_a_draft_is_422(api_client: httpx.AsyncClient) -> None:
    draft = await _create_draft(api_client)

    response = await api_client.post(
        f"/api/v1/feature-configs/{draft['feature_config_id']}/clone", json={"name": "Copy"}
    )

    assert response.status_code == 422
    assert response.json()["validation_errors"]


async def test_clone_of_a_frozen_set_creates_an_independent_draft(
    api_client: httpx.AsyncClient,
) -> None:
    draft = await _create_draft(api_client)
    await _add_feature(api_client, draft["feature_config_id"], key="weather", value_type="integer")
    frozen = (
        await api_client.post(f"/api/v1/feature-configs/{draft['feature_config_id']}/freeze")
    ).json()

    response = await api_client.post(
        f"/api/v1/feature-configs/{frozen['feature_config_id']}/clone",
        json={"name": "Weather & conditions"},
    )

    assert response.status_code == 201
    clone = response.json()
    assert clone["feature_config_id"] != frozen["feature_config_id"]
    assert clone["frozen_at"] is None
    assert clone["version"] == 2
    assert [f["key"] for f in clone["features"]] == ["weather"]
    assert clone["features"][0]["feature_id"] != frozen["features"][0]["feature_id"]
    assert clone["features"][0]["fingerprint"] is None

    # Independent: editing the clone must not touch the frozen original.
    await api_client.delete(
        f"/api/v1/feature-configs/{clone['feature_config_id']}"
        f"/features/{clone['features'][0]['feature_id']}"
    )
    original = await api_client.get(f"/api/v1/feature-configs/{frozen['feature_config_id']}")
    assert [f["key"] for f in original.json()["features"]] == ["weather"]


async def test_clone_of_an_unknown_config_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/feature-configs/no-such-config/clone", json={"name": "Copy"}
    )
    assert response.status_code == 404
