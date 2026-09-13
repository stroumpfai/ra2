"""`/api/v1/prompt-templates` through `httpx.ASGITransport` — no network (K1).

Thin-router plumbing over `PromptService` (I1, Wave 2): every conversion
between the wire schemas (`ra2/api/schemas.py`) and the service's read models
(`ra2/services/readmodels.py`) lives in `ra2/api/v1/prompt_templates.py`.
`PromptService`'s own behaviour (validation, copy-on-write, the citation
guard, the feature-block rendering) is I1's, asserted in
`tests/backend/services/prompt/**` — not re-asserted here beyond what the
wire layer must preserve.

`api_client` comes from `tests/backend/api/conftest.py` (shared across every
`tests/backend/api/**` suite, same as `tests/backend/api/features/**`).
"""

from collections.abc import Awaitable, Callable

import httpx
import pytest

pytestmark = pytest.mark.backend

SeedTemplate = Callable[..., Awaitable[str]]
SeedRecord = Callable[..., Awaitable[str]]
SeedFeatureConfig = Callable[..., Awaitable[str]]
SeedCitedTemplate = Callable[..., Awaitable[str]]

VALID_SOURCE = "Describe {{narrative}} using {{feature_block}} in {{language}}."


# ---------------------------------------------------------------------------
# list / get / slots
# ---------------------------------------------------------------------------


async def test_list_versions_starts_empty(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/prompt-templates")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_versions_returns_every_row_newest_first(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    await seed_template("pt-1", version=1)
    await seed_template("pt-2", version=2)

    response = await api_client.get("/api/v1/prompt-templates")

    assert response.status_code == 200
    body = response.json()
    assert [v["prompt_template_id"] for v in body] == ["pt-2", "pt-1"]
    assert body[0]["version"] == 2
    assert body[0]["is_active"] is False
    assert body[0]["cited_by_run_count"] == 0
    assert body[0]["deletable"] is True
    assert body[0]["fingerprint"]


async def test_get_version_returns_it(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    await seed_template("pt-1", version=1, source=VALID_SOURCE)

    response = await api_client.get("/api/v1/prompt-templates/pt-1")

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_template_id"] == "pt-1"
    assert body["source"] == VALID_SOURCE


async def test_get_unknown_version_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/prompt-templates/no-such-template")
    assert response.status_code == 404


async def test_list_slots_returns_the_closed_catalogue(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/prompt-templates/slots")

    assert response.status_code == 200
    body = response.json()
    names = {s["name"] for s in body}
    assert names == {"feature_block", "narrative", "language"}
    required = {s["name"] for s in body if s["required"]}
    assert required == {"feature_block", "narrative"}


# ---------------------------------------------------------------------------
# save as next version (copy-on-write)
# ---------------------------------------------------------------------------


async def test_save_as_next_version_creates_v1_when_none_exist(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post("/api/v1/prompt-templates", json={"source": VALID_SOURCE})

    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["source"] == VALID_SOURCE
    assert body["is_active"] is False
    assert body["cited_by_run_count"] == 0
    assert body["deletable"] is True
    assert body["fingerprint"]


async def test_save_as_next_version_never_mutates_the_previous_row(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    await seed_template("pt-1", version=1, source=VALID_SOURCE)

    response = await api_client.post(
        "/api/v1/prompt-templates", json={"source": VALID_SOURCE + " v2"}
    )

    assert response.status_code == 201
    assert response.json()["version"] == 2

    original = await api_client.get("/api/v1/prompt-templates/pt-1")
    assert original.json()["source"] == VALID_SOURCE  # byte-identical, untouched


async def test_save_with_a_missing_required_slot_is_422_with_typed_errors(
    api_client: httpx.AsyncClient,
) -> None:
    """An invalid template is 422 with the typed validation errors, not a
    500 — the router's central exit criterion."""
    response = await api_client.post(
        "/api/v1/prompt-templates", json={"source": "No slots here at all."}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "invalid prompt template; nothing was saved"
    codes = {e["code"] for e in body["validation_errors"]}
    assert "missing_required_slot" in codes
    for error in body["validation_errors"]:
        assert "code" in error

    # Nothing was written.
    assert (await api_client.get("/api/v1/prompt-templates")).json() == []


async def test_save_with_an_unknown_slot_is_422(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/prompt-templates",
        json={"source": "{{narrative}} {{feature_block}} {{not_a_real_slot}}"},
    )

    assert response.status_code == 422
    codes = {e["code"] for e in response.json()["validation_errors"]}
    assert "unknown_slot" in codes


async def test_save_with_an_empty_source_is_422(api_client: httpx.AsyncClient) -> None:
    """`CreatePromptTemplateRequest.source` has `min_length=1`, so an empty
    body is refused by Pydantic before the service ever validates it — still
    422, still no 500."""
    response = await api_client.post("/api/v1/prompt-templates", json={"source": ""})
    assert response.status_code == 422


async def test_no_patch_or_put_route_exists(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    """**The absence is the contract** (sw-design.md §15.1): saving is
    copy-on-write, so a version can never be edited in place."""
    await seed_template("pt-1", version=1)

    patch_response = await api_client.patch(
        "/api/v1/prompt-templates/pt-1", json={"source": "anything"}
    )
    put_response = await api_client.put(
        "/api/v1/prompt-templates/pt-1", json={"source": "anything"}
    )

    assert patch_response.status_code == 405
    assert put_response.status_code == 405


# ---------------------------------------------------------------------------
# activate
# ---------------------------------------------------------------------------


async def test_activate_marks_exactly_one_version_active(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    await seed_template("pt-1", version=1)
    await seed_template("pt-2", version=2)

    first = await api_client.post("/api/v1/prompt-templates/pt-1/activate")
    assert first.status_code == 200
    assert first.json()["is_active"] is True

    second = await api_client.post("/api/v1/prompt-templates/pt-2/activate")
    assert second.status_code == 200
    assert second.json()["is_active"] is True

    now_inactive = await api_client.get("/api/v1/prompt-templates/pt-1")
    assert now_inactive.json()["is_active"] is False


async def test_activate_unknown_version_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post("/api/v1/prompt-templates/no-such-template/activate")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_removes_an_uncited_version(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate
) -> None:
    await seed_template("pt-1", version=1)

    response = await api_client.delete("/api/v1/prompt-templates/pt-1")

    assert response.status_code == 204
    assert response.content == b""
    assert (await api_client.get("/api/v1/prompt-templates/pt-1")).status_code == 404


async def test_delete_unknown_version_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.delete("/api/v1/prompt-templates/no-such-template")
    assert response.status_code == 404


async def test_delete_a_cited_version_is_409_and_deletes_nothing(
    api_client: httpx.AsyncClient, seed_cited_template: SeedCitedTemplate
) -> None:
    """Deleting a cited version returns 409 — the router's second central
    exit criterion."""
    await seed_cited_template("pt-1")

    response = await api_client.delete("/api/v1/prompt-templates/pt-1")

    assert response.status_code == 409
    assert (await api_client.get("/api/v1/prompt-templates/pt-1")).status_code == 200


# ---------------------------------------------------------------------------
# resolve (the shared no-model-call preview, C4)
# ---------------------------------------------------------------------------


async def test_resolve_renders_the_narrative_and_feature_block(
    api_client: httpx.AsyncClient,
    seed_template: SeedTemplate,
    seed_minimal_feature_config: SeedFeatureConfig,
    seed_record: SeedRecord,
) -> None:
    await seed_template("pt-1", version=1, source=VALID_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1")
    await seed_record("rec-1", corpus_id="corpus-1", text_raw="Es regnete stark.")

    response = await api_client.post(
        "/api/v1/prompt-templates/resolve",
        json={
            "prompt_template_id": "pt-1",
            "feature_config_id": config_id,
            "record_id": "rec-1",
            "language": "de",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "Es regnete stark." in body["text"]
    assert "injured_count" in body["text"]
    assert body["record_key"] == "uid-0001"
    assert body["feature_count"] == 1
    assert body["token_estimate"] > 0
    assert set(body["slots_used"]) == {"narrative", "feature_block", "language"}
    assert body["validation_errors"] == []


async def test_resolve_defaults_language_when_omitted(
    api_client: httpx.AsyncClient,
    seed_template: SeedTemplate,
    seed_minimal_feature_config: SeedFeatureConfig,
    seed_record: SeedRecord,
) -> None:
    """`ResolvePromptRequest.language` defaults to `"de"` — omitting it must
    not 422, and the resolved text reflects the default."""
    await seed_template("pt-1", version=1, source="{{narrative}} {{feature_block}} {{language}}")
    config_id = await seed_minimal_feature_config("fc-1")
    await seed_record("rec-1", corpus_id="corpus-1")

    response = await api_client.post(
        "/api/v1/prompt-templates/resolve",
        json={
            "prompt_template_id": "pt-1",
            "feature_config_id": config_id,
            "record_id": "rec-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["text"].endswith("de")


async def test_resolve_unknown_template_is_404(
    api_client: httpx.AsyncClient,
    seed_minimal_feature_config: SeedFeatureConfig,
    seed_record: SeedRecord,
) -> None:
    config_id = await seed_minimal_feature_config("fc-1")
    await seed_record("rec-1", corpus_id="corpus-1")

    response = await api_client.post(
        "/api/v1/prompt-templates/resolve",
        json={
            "prompt_template_id": "no-such-template",
            "feature_config_id": config_id,
            "record_id": "rec-1",
        },
    )

    assert response.status_code == 404


async def test_resolve_unknown_feature_config_is_404(
    api_client: httpx.AsyncClient, seed_template: SeedTemplate, seed_record: SeedRecord
) -> None:
    await seed_template("pt-1", version=1, source=VALID_SOURCE)
    await seed_record("rec-1", corpus_id="corpus-1")

    response = await api_client.post(
        "/api/v1/prompt-templates/resolve",
        json={
            "prompt_template_id": "pt-1",
            "feature_config_id": "no-such-config",
            "record_id": "rec-1",
        },
    )

    assert response.status_code == 404


async def test_resolve_unknown_record_is_404(
    api_client: httpx.AsyncClient,
    seed_template: SeedTemplate,
    seed_minimal_feature_config: SeedFeatureConfig,
) -> None:
    await seed_template("pt-1", version=1, source=VALID_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1")

    response = await api_client.post(
        "/api/v1/prompt-templates/resolve",
        json={
            "prompt_template_id": "pt-1",
            "feature_config_id": config_id,
            "record_id": "no-such-record",
        },
    )

    assert response.status_code == 404
