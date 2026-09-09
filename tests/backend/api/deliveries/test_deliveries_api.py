"""`/api/v1/deliveries` through `httpx.ASGITransport` — no network (C1, M4).

Thin-router assertions only: does the request reach the service, does the
service's read model come back mapped onto the wire schema, does a service
error become the right HTTP status. The parsing/analysis behaviour itself is
B1's, asserted in `tests/backend/services/delivery/**`.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.backend

HazardBytes = Callable[[str, str], bytes]


async def test_list_deliveries_starts_empty(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/deliveries")
    assert response.status_code == 200
    assert response.json() == []


async def test_register_upload_delivery_returns_the_full_view(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG 2025", "source_kind": "upload"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "AG 2025"
    assert body["source_kind"] == "upload"
    assert body["root_path"] is None
    assert body["status"] == "registered"
    assert body["files"] == []
    assert body["selected_record_count"] == 0
    assert "delivery_id" in body

    listed = await api_client.get("/api/v1/deliveries")
    assert [d["delivery_id"] for d in listed.json()] == [body["delivery_id"]]


async def test_register_host_path_delivery_lists_the_files_in_place(
    api_client: httpx.AsyncClient, hazards_dir: Path
) -> None:
    root = hazards_dir / "h10_count_mismatch"
    response = await api_client.post(
        "/api/v1/deliveries",
        json={"name": "on disk", "source_kind": "host_path", "root_path": root.as_posix()},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["source_kind"] == "host_path"
    assert body["root_path"] == root.as_posix()
    assert sorted(f["filename"] for f in body["files"]) == [
        "objekt.txt",
        "person.txt",
        "unfall.txt",
    ]


async def test_get_delivery_round_trips_what_register_returned(
    api_client: httpx.AsyncClient,
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]

    response = await api_client.get(f"/api/v1/deliveries/{delivery_id}")
    assert response.status_code == 200
    assert response.json() == registered.json()


async def test_get_unknown_delivery_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/deliveries/no-such-delivery")
    assert response.status_code == 404


async def test_upload_file_streams_the_bytes_and_appears_in_the_delivery(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    data = hazard_bytes("h10_count_mismatch", "unfall.txt")

    response = await api_client.post(
        f"/api/v1/deliveries/{delivery_id}/files",
        files={"file": ("unfall.txt", data, "text/plain")},
    )
    assert response.status_code == 200
    file_body = response.json()
    assert file_body["filename"] == "unfall.txt"
    assert file_body["byte_size"] == len(data)
    # Not analysed yet: analyse is a separate phase (sw-design.md §6.2).
    assert file_body["row_count"] is None
    assert file_body["analysed_at"] is None

    delivery = await api_client.get(f"/api/v1/deliveries/{delivery_id}")
    assert [f["filename"] for f in delivery.json()["files"]] == ["unfall.txt"]


async def test_upload_file_to_an_unknown_delivery_is_404(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    data = hazard_bytes("h10_count_mismatch", "unfall.txt")
    response = await api_client.post(
        "/api/v1/deliveries/no-such-delivery/files",
        files={"file": ("unfall.txt", data, "text/plain")},
    )
    assert response.status_code == 404


async def test_analyse_delivery_marks_files_analysed_and_returns_a_task_id(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    await api_client.post(
        f"/api/v1/deliveries/{delivery_id}/files",
        files={
            "file": ("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt"), "text/plain")
        },
    )

    response = await api_client.post(f"/api/v1/deliveries/{delivery_id}/analyse")
    assert response.status_code == 200
    assert response.json()["task_id"]

    # `InlineTaskRunner` finished synchronously, so the effect is already
    # visible without polling `GET /api/v1/tasks/{id}` (C2, not under test here).
    delivery = (await api_client.get(f"/api/v1/deliveries/{delivery_id}")).json()
    assert delivery["status"] == "analysed"
    (file_row,) = delivery["files"]
    assert file_row["file_kind"] == "unfall"
    assert file_row["analysed_at"] is not None
    assert file_row["row_count"] is not None


async def test_analyse_unknown_delivery_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post("/api/v1/deliveries/no-such-delivery/analyse")
    assert response.status_code == 404


async def test_override_and_reparse_updates_only_the_named_file(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    for filename in ("unfall.txt", "objekt.txt"):
        await api_client.post(
            f"/api/v1/deliveries/{delivery_id}/files",
            files={"file": (filename, hazard_bytes("h10_count_mismatch", filename), "text/plain")},
        )
    await api_client.post(f"/api/v1/deliveries/{delivery_id}/analyse")
    before = (await api_client.get(f"/api/v1/deliveries/{delivery_id}")).json()
    other_before = next(f for f in before["files"] if f["filename"] == "objekt.txt")
    target = next(f for f in before["files"] if f["filename"] == "unfall.txt")

    response = await api_client.patch(
        f"/api/v1/deliveries/{delivery_id}/files/{target['file_id']}",
        json={"encoding": "utf-8"},
    )
    assert response.status_code == 200
    reparsed = response.json()
    assert reparsed["file_id"] == target["file_id"]
    assert reparsed["encoding"] == "utf-8"
    assert reparsed["row_count"] == target["row_count"]

    after = (await api_client.get(f"/api/v1/deliveries/{delivery_id}")).json()
    other_after = next(f for f in after["files"] if f["filename"] == "objekt.txt")
    assert other_after == other_before


async def test_override_unknown_file_is_404(api_client: httpx.AsyncClient) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    response = await api_client.patch(
        f"/api/v1/deliveries/{delivery_id}/files/no-such-file",
        json={"encoding": "utf-8"},
    )
    assert response.status_code == 404


async def test_set_file_selection_recomputes_the_delivery_record_count(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    await api_client.post(
        f"/api/v1/deliveries/{delivery_id}/files",
        files={
            "file": (
                "unfall.txt",
                hazard_bytes("h10_count_mismatch", "unfall.txt"),
                "text/plain",
            )
        },
    )
    await api_client.post(f"/api/v1/deliveries/{delivery_id}/analyse")
    delivery = (await api_client.get(f"/api/v1/deliveries/{delivery_id}")).json()
    assert delivery["selected_record_count"] > 0
    (file_row,) = delivery["files"]

    response = await api_client.put(
        f"/api/v1/deliveries/{delivery_id}/files/{file_row['file_id']}/selection",
        json={"selected": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["selected_record_count"] == 0
    assert body["files"][0]["selected"] is False


async def test_set_selection_on_unknown_file_is_404(api_client: httpx.AsyncClient) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    response = await api_client.put(
        f"/api/v1/deliveries/{delivery_id}/files/no-such-file/selection",
        json={"selected": False},
    )
    assert response.status_code == 404


async def test_remove_file_drops_it_from_the_delivery(
    api_client: httpx.AsyncClient, hazard_bytes: HazardBytes
) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    uploaded = await api_client.post(
        f"/api/v1/deliveries/{delivery_id}/files",
        files={
            "file": (
                "unfall.txt",
                hazard_bytes("h10_count_mismatch", "unfall.txt"),
                "text/plain",
            )
        },
    )
    file_id = uploaded.json()["file_id"]

    response = await api_client.delete(f"/api/v1/deliveries/{delivery_id}/files/{file_id}")
    assert response.status_code == 204
    assert response.content == b""

    delivery = (await api_client.get(f"/api/v1/deliveries/{delivery_id}")).json()
    assert delivery["files"] == []


async def test_remove_unknown_file_is_404(api_client: httpx.AsyncClient) -> None:
    registered = await api_client.post(
        "/api/v1/deliveries", json={"name": "AG", "source_kind": "upload"}
    )
    delivery_id = registered.json()["delivery_id"]
    response = await api_client.delete(f"/api/v1/deliveries/{delivery_id}/files/no-such-file")
    assert response.status_code == 404
