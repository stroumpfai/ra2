"""`POST /api/v1/deliveries` answers 422 for a refused host path (`SD49`).

The API layer's conftest injects an unconstrained store; this module
overrides that fixture with one constrained the way `create_app()` builds it
from `Settings`, so the refusal reaches the wire.
"""

from pathlib import Path

import httpx
import pytest

from ra2.infra.filestore import HostPathFileStore

pytestmark = pytest.mark.backend


@pytest.fixture
def api_host_path_store(tmp_path: Path) -> HostPathFileStore:
    return HostPathFileStore(allowed_root=tmp_path / "import", max_files=200)


async def test_a_host_path_outside_the_import_root_is_a_422_and_nothing_is_listed(
    api_client: httpx.AsyncClient, hazards_dir: Path
) -> None:
    response = await api_client.post(
        "/api/v1/deliveries",
        json={
            "name": "outside",
            "source_kind": "host_path",
            "root_path": (hazards_dir / "h10_count_mismatch").as_posix(),
        },
    )

    # The code on the wire is the status; the sentence is for a person.
    assert response.status_code == 422
    assert (await api_client.get("/api/v1/deliveries")).json() == []
