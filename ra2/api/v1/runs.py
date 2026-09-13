# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/runs` — the runs table, one run's progress, and Resume
(plan-phase-3.md §9, sw-design.md §15.4).

Resume is **explicit**: an interrupted run stays interrupted until someone
presses the button. Nothing auto-restarts at startup (§15 F8).
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import RunServiceDep
from ra2.api.schemas import (
    RunPage,
    RunProgressResponse,
    RunResponse,
    TaskAcceptedResponse,
)
from ra2.services.readmodels import SortDir

__all__ = ["router"]

router = APIRouter(prefix="/runs", tags=["runs"])

_NOT_BUILT = "not implemented until Wave 3 (K2)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=RunPage)
async def list_runs(
    evaluation_id: str,
    service: RunServiceDep,
    page: int = 1,
    page_size: int = 10,
    sort_key: str = "started_at",
    sort_dir: SortDir = SortDir.DESC,
) -> RunPage:
    """The "Runs in this evaluation" table — paginated at 10, as drawn."""
    raise _todo()


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, service: RunServiceDep) -> RunResponse:
    raise _todo()


@router.get("/{run_id}/progress", response_model=RunProgressResponse)
async def get_progress(run_id: str, service: RunServiceDep) -> RunProgressResponse:
    """Derived from committed `extraction` rows, never from a counter."""
    raise _todo()


@router.post("/{run_id}/resume", response_model=TaskAcceptedResponse)
async def resume(run_id: str, service: RunServiceDep) -> TaskAcceptedResponse:
    """Pick an interrupted run back up from its last committed extraction."""
    raise _todo()
