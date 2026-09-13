# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/runs` — the runs table, one run's progress, and Resume
(plan-phase-3.md §9, sw-design.md §15.4).

Resume is **explicit**: an interrupted run stays interrupted until someone
presses the button. Nothing auto-restarts at startup (§15 F8). Thin
translation only, same idiom as `evaluations.py`/`features.py`.
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import RunServiceDep
from ra2.api.schemas import (
    PageMeta,
    RunPage,
    RunProgressResponse,
    RunResponse,
    TaskAcceptedResponse,
)
from ra2.domain.ids import EvaluationId, RunId
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import Page, RunProgressView, RunView, SortDir

__all__ = ["router"]

router = APIRouter(prefix="/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _run_response(view: RunView) -> RunResponse:
    return RunResponse(
        run_id=view.run_id,
        evaluation_id=view.evaluation_id,
        model_tag=view.model_tag,
        model_digest=view.model_digest,
        records_done=view.records_done,
        started_at=view.started_at,
        status=view.status,
        is_dev=view.is_dev,
        error=view.error,
    )


def _run_page_response(page: Page[RunView]) -> RunPage:
    return RunPage(
        items=[_run_response(r) for r in page.items],
        meta=PageMeta(
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            sort_key=page.sort_key,
            sort_dir=page.sort_dir,
        ),
    )


def _run_progress_response(view: RunProgressView) -> RunProgressResponse:
    return RunProgressResponse(
        run_id=view.run_id,
        model_tag=view.model_tag,
        status=view.status,
        done=view.done,
        total=view.total,
        percent=view.percent,
        parse_failures=view.parse_failures,
        retries=view.retries,
        median_latency_ms=view.median_latency_ms,
        prompt_tokens=view.prompt_tokens,
        elapsed_ms=view.elapsed_ms,
        eta_ms=view.eta_ms,
    )


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


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
    result = await service.list_runs(
        EvaluationId(evaluation_id),
        page=page,
        page_size=page_size,
        sort_key=sort_key,
        sort_dir=sort_dir,
    )
    return _run_page_response(result)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, service: RunServiceDep) -> RunResponse:
    try:
        view = await service.get(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _run_response(view)


@router.get("/{run_id}/progress", response_model=RunProgressResponse)
async def get_progress(run_id: str, service: RunServiceDep) -> RunProgressResponse:
    """Derived from committed `extraction` rows, never from a counter."""
    try:
        view = await service.progress(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _run_progress_response(view)


@router.post("/{run_id}/resume", response_model=TaskAcceptedResponse)
async def resume(run_id: str, service: RunServiceDep) -> TaskAcceptedResponse:
    """Pick an interrupted run back up from its last committed extraction."""
    try:
        task_id = await service.resume(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return TaskAcceptedResponse(task_id=str(task_id))
