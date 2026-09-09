"""`/api/v1/corpora` through `httpx.ASGITransport` — no network (C1, M4).

The two contracts that matter at this layer (plan-m0-m5.md §7):
- a blocking freeze returns **422 with the findings** and creates nothing (J2);
- `DELETE` on a corpus an evaluation cites returns **409** (J3).

Everything else is thin-router plumbing; `CorpusService.freeze()`'s own
behaviour is B1's, asserted in `tests/backend/services/corpus/**`.
"""

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.persistence.models import Corpus, Evaluation

pytestmark = pytest.mark.backend

HazardBytes = Callable[[str, str], bytes]


async def _upload_and_analyse(
    api_client: httpx.AsyncClient, hazard: str, filenames: list[str], hazard_bytes: HazardBytes
) -> str:
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


async def test_list_corpora_starts_empty(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/corpora")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["meta"] == {
        "total": 0,
        "page": 1,
        "page_size": 10,
        "sort_key": "imported_at",
        "sort_dir": "desc",
    }


async def test_create_corpus_freezes_the_selected_files(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    delivery_id = await _upload_and_analyse(
        api_client,
        "h10_count_mismatch",
        ["unfall.txt", "objekt.txt", "person.txt"],
        hazard_bytes,
    )

    response = await api_client.post(
        "/api/v1/corpora",
        json={"delivery_id": delivery_id, "name": "AG corpus", "description": "first freeze"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "AG corpus"
    assert body["description"] == "first freeze"
    assert body["version"] == 1
    assert body["record_count"] == 1
    assert body["delivery_id"] == delivery_id
    assert body["locked_by_evaluations"] == 0

    fetched = await api_client.get(f"/api/v1/corpora/{body['corpus_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    listed = await api_client.get("/api/v1/corpora")
    assert [c["corpus_id"] for c in listed.json()["items"]] == [body["corpus_id"]]
    assert listed.json()["meta"]["total"] == 1


async def test_create_corpus_blocking_returns_422_with_findings_and_creates_nothing(
    api_client: httpx.AsyncClient,
    hazard_bytes: HazardBytes,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """h07: the same `UnfallUid` in two cantonal sets — blocking (mvp-spec.md §4.3)."""
    delivery_id = await _upload_and_analyse(
        api_client,
        "h07_dup_uid_cross_canton",
        ["ag_unfall.txt", "be_unfall.txt"],
        hazard_bytes,
    )

    response = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": delivery_id, "name": "dup"}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["findings"], "expected the blocking findings in the body"
    assert all(f["severity"] == "BLOCKING" for f in body["findings"])
    assert any(f["code"] == "DUP_KEY_CROSS_SET" for f in body["findings"])

    async with db_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Corpus))
    assert count == 0

    listed = await api_client.get("/api/v1/corpora")
    assert listed.json()["items"] == []


async def test_create_corpus_for_an_unanalysed_delivery_is_409(
    api_client: httpx.AsyncClient,
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "too early", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]

    response = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": delivery_id, "name": "too early"}
    )
    assert response.status_code == 409


async def test_create_corpus_for_an_unknown_delivery_is_404(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": "no-such-delivery", "name": "x"}
    )
    assert response.status_code == 404


async def test_get_unknown_corpus_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/corpora/no-such-corpus")
    assert response.status_code == 404


async def test_delete_corpus_removes_it(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    delivery_id = await _upload_and_analyse(
        api_client,
        "h10_count_mismatch",
        ["unfall.txt", "objekt.txt", "person.txt"],
        hazard_bytes,
    )
    created = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": delivery_id, "name": "throwaway"}
    )
    corpus_id = created.json()["corpus_id"]

    response = await api_client.delete(f"/api/v1/corpora/{corpus_id}")
    assert response.status_code == 204
    assert response.content == b""

    assert (await api_client.get(f"/api/v1/corpora/{corpus_id}")).status_code == 404


async def test_delete_unknown_corpus_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.delete("/api/v1/corpora/no-such-corpus")
    assert response.status_code == 404


async def test_delete_corpus_cited_by_an_evaluation_is_409(
    api_client: httpx.AsyncClient,
    hazard_bytes: HazardBytes,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """J3: an evaluation citing a corpus refuses the delete."""
    delivery_id = await _upload_and_analyse(
        api_client,
        "h10_count_mismatch",
        ["unfall.txt", "objekt.txt", "person.txt"],
        hazard_bytes,
    )
    created = await api_client.post(
        "/api/v1/corpora", json={"delivery_id": delivery_id, "name": "cited"}
    )
    corpus_id = created.json()["corpus_id"]

    async with db_session_factory() as session:
        session.add(
            Evaluation(id=EvaluationId("eval-1"), name="eval-1", corpus_id=CorpusId(corpus_id))
        )
        await session.commit()

    response = await api_client.delete(f"/api/v1/corpora/{corpus_id}")
    assert response.status_code == 409

    # Refused, not partially applied: the corpus is still there.
    still_there = await api_client.get(f"/api/v1/corpora/{corpus_id}")
    assert still_there.status_code == 200
    assert still_there.json()["locked_by_evaluations"] == 1


async def test_list_corpora_sorts_and_pages(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    for name in ("b corpus", "a corpus"):
        delivery_id = await _upload_and_analyse(
            api_client,
            "h10_count_mismatch",
            ["unfall.txt", "objekt.txt", "person.txt"],
            hazard_bytes,
        )
        await api_client.post("/api/v1/corpora", json={"delivery_id": delivery_id, "name": name})

    response = await api_client.get(
        "/api/v1/corpora", params={"sort_key": "name", "sort_dir": "asc", "page": 1, "page_size": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2
    assert body["meta"]["sort_key"] == "name"
    assert body["meta"]["sort_dir"] == "asc"
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "a corpus"
