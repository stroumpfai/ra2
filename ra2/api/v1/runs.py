# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/runs` — the runs table, one run's progress, and Resume
(plan-phase-3.md §9, sw-design.md §15.4).

Resume is **explicit**: an interrupted run stays interrupted until someone
presses the button. Nothing auto-restarts at startup (§15 F8). Thin
translation only, same idiom as `evaluations.py`/`features.py`.
"""

from fastapi import APIRouter, HTTPException, Response, status

from ra2.api.deps import ExportServiceDep, LifecycleServiceDep, RunServiceDep
from ra2.api.schemas import (
    DiscardPreview,
    DiscardResponse,
    ErrorResponse,
    PageMeta,
    RunPage,
    RunProgressResponse,
    RunResponse,
    TaskAcceptedResponse,
)
from ra2.api.v1.discard import conflict, discard_response
from ra2.api.v1.discard import discard_preview as to_preview
from ra2.domain.ids import EvaluationId, RunId
from ra2.services.errors import (
    NotFoundError,
    RunActiveError,
    RunNotActiveError,
    TaggedWorkPresentError,
)
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


@router.post(
    "/{run_id}/cancel",
    response_model=RunResponse,
    responses={409: {"model": ErrorResponse}},
)
async def cancel(run_id: str, service: RunServiceDep) -> RunResponse:
    """Stop a `queued` or `running` run, keeping whatever it committed.

    `Resume`'s mirror, and it answers with the run rather than a task id:
    `resume` *starts* work and hands back something to poll, this one ends it,
    and the useful reply is the state the run is now in.

    409 when the run is neither `queued` nor `running` — `RunActiveError`'s
    guard from the other side. Succeeding there would rewrite a finished run's
    outcome as an interruption that never happened.
    """
    key = RunId(run_id)
    try:
        await service.cancel(key)
        view = await service.get(key)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except RunNotActiveError as exc:
        raise conflict(exc) from exc
    return _run_response(view)


# ---------------------------------------------------------------------------
# discard — sw-design.md §18
# ---------------------------------------------------------------------------


@router.get("/{run_id}/discard-preview", response_model=DiscardPreview)
async def discard_preview(run_id: str, service: LifecycleServiceDep) -> DiscardPreview:
    """What discarding this run would destroy. Counts only; writes nothing."""
    try:
        view = await service.run_preview(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return to_preview(view)


@router.get("/{run_id}/scores.csv")
async def export_scores(
    run_id: str, lifecycle: LifecycleServiceDep, export: ExportServiceDep
) -> Response:
    """Export before discard (§18.3) — UTF-8 with BOM, `;`-delimited."""
    try:
        view = await lifecycle.run_export(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(content=export.run_scores_csv(view), media_type="text/csv")


@router.get("/{run_id}/mismatches.csv")
async def export_mismatches(
    run_id: str, lifecycle: LifecycleServiceDep, export: ExportServiceDep
) -> Response:
    """The half a re-run cannot reproduce: `analyst_tag` and its note."""
    try:
        view = await lifecycle.run_export(RunId(run_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(content=export.run_mismatches_csv(view), media_type="text/csv")


@router.delete(
    "/{run_id}",
    response_model=DiscardResponse,
    responses={409: {"model": ErrorResponse}},
)
async def discard_run(
    run_id: str, service: LifecycleServiceDep, force: bool = False
) -> DiscardResponse:
    """Discard one run and, by the schema's cascade, everything derived from
    it (§18.1).

    409 when the run is `queued` or `running` (G1), and when it carries tagged
    mismatches and `force` was not passed (G2). The second is overridable; the
    first is not.

    The preview is read **first**, inside the same request, because after the
    delete those counts do not exist anywhere — this response is the receipt.
    """
    key = RunId(run_id)
    try:
        before = await service.run_preview(key)
        await service.discard_run(key, force=force)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except (RunActiveError, TaggedWorkPresentError) as exc:
        raise conflict(exc) from exc
    return discard_response(before, forced=force and before.tagged_mismatches > 0)
