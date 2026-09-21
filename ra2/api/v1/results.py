# STUB — bodies owned by U1 (feat/p4-api-results). Not frozen.
"""`/api/v1/evaluations/{id}/results` — tab 1, plus scoring status and re-score
(plan-phase-4.md §9, sw-design.md §16.7).

**An unscored run is 200 with `scored: false`, never a 404.** The UI renders a
state, and an error status would force exactly the toast §16.7 rejects — the
same reasoning §15.5 applied to an unreachable endpoint, and the same shape
`GET /api/v1/models` already has.

**A suppressed cell never serialises as a number.** It goes out as its typed
insufficient-data shape carrying its `n` and the floor, and U1's tests assert
the absence at the JSON layer as well as the DOM: four layers, four chances to
leak a number nobody measured.

Thin translation only, same idiom as `runs.py`/`evaluations.py`.
"""

from fastapi import APIRouter, HTTPException, Query, status

from ra2.api.deps import ResultsServiceDep, ScoringServiceDep
from ra2.api.schemas import (
    BreakdownResponse,
    BreakdownRowResponse,
    ByLanguageResponse,
    ByLanguageRowResponse,
    CellResponse,
    ExtractionTabResponse,
    FeatureScorePage,
    FeatureScoreResponse,
    ModelColumnResponse,
    RunDescriptorResponse,
    ScoringStatusResponse,
    TaskAcceptedResponse,
)
from ra2.domain.ids import EvaluationId, FeatureId, RunId
from ra2.services.errors import NotFoundError, RunNotScoreableError
from ra2.services.readmodels import (
    BreakdownView,
    ByLanguageView,
    Cell,
    ExtractionTabView,
    FeatureScoreRow,
    RunDescriptorView,
    ScoringStatusView,
    SortDir,
    SuppressedCell,
)

__all__ = ["cell_response", "descriptor_response", "router"]

router = APIRouter(tags=["results"])


# ---------------------------------------------------------------------------
# read model -> wire schema. Shared with `presence.py` and `ranking.py`, which
# render the same cells and the same descriptor — two copies would be two
# chances to let a suppressed cell out as a number.
# ---------------------------------------------------------------------------


def cell_response(cell: Cell) -> CellResponse:
    """**Where §11.4 is enforced on the wire.**

    A suppressed cell serialises with `value`, `ci_low` and `ci_high` absent.
    A client that forgets to check `suppressed` gets `null`, not a plausible
    number nobody measured.
    """
    if isinstance(cell, SuppressedCell):
        return CellResponse(suppressed=True, n=cell.n, floor=cell.floor)
    return CellResponse(
        suppressed=False,
        n=cell.n,
        value=cell.value,
        ci_low=cell.ci_low,
        ci_high=cell.ci_high,
        mark=cell.mark.value,
    )


def descriptor_response(view: RunDescriptorView) -> RunDescriptorResponse:
    return RunDescriptorResponse(
        evaluation_id=view.evaluation_id,
        corpus_label=view.corpus_label,
        record_count=view.record_count,
        model_count=view.model_count,
        config_fingerprint=view.config_fingerprint,
        is_dev=view.is_dev,
        min_cell_count=view.min_cell_count,
    )


def _feature_row(row: FeatureScoreRow) -> FeatureScoreResponse:
    return FeatureScoreResponse(
        feature_id=row.feature_id,
        name=row.name,
        source_label=row.source_label,
        n=row.n,
        suppressed=row.suppressed,
        cells={model_id: cell_response(cell) for model_id, cell in row.cells.items()},
    )


def _breakdown(view: BreakdownView) -> BreakdownResponse:
    return BreakdownResponse(
        feature_id=view.feature_id,
        feature_name=view.feature_name,
        rows=[
            BreakdownRowResponse(
                model_id=row.model_id,
                precision=row.precision,
                recall=row.recall,
                f1=row.f1,
                hit=row.hit,
                wrong=row.wrong,
                missing=row.missing,
            )
            for row in view.rows
        ],
    )


def _by_language(view: ByLanguageView) -> ByLanguageResponse:
    return ByLanguageResponse(
        feature_id=view.feature_id,
        feature_name=view.feature_name,
        model_id=view.model_id,
        rows=[
            ByLanguageRowResponse(language=row.language, cell=cell_response(row.cell))
            for row in view.rows
        ],
    )


def _extraction_tab(view: ExtractionTabView, *, scored: bool) -> ExtractionTabResponse:
    return ExtractionTabResponse(
        scored=scored,
        descriptor=descriptor_response(view.descriptor),
        models=[
            ModelColumnResponse(model_id=m.model_id, tag=m.tag, digest=m.digest)
            for m in view.models
        ],
        features=FeatureScorePage(
            items=[_feature_row(row) for row in view.features.items],
            total=view.features.total,
            page=view.features.page,
            page_size=view.features.page_size,
            sort_key=view.features.sort_key,
            sort_dir=view.features.sort_dir,
        ),
        breakdown=_breakdown(view.breakdown) if view.breakdown else None,
        by_language=_by_language(view.by_language) if view.by_language else None,
    )


def _status(view: ScoringStatusView) -> ScoringStatusResponse:
    return ScoringStatusResponse(
        run_id=view.run_id,
        scored_features=view.scored_features,
        labelled_features=view.labelled_features,
        running=view.running,
        is_scored=view.is_scored,
        is_scoreable=view.is_scoreable,
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("/evaluations/{evaluation_id}/scoring-status")
async def scoring_status(
    evaluation_id: str, service: ResultsServiceDep
) -> list[ScoringStatusResponse]:
    try:
        views = await service.scoring_status(EvaluationId(evaluation_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return [_status(view) for view in views]


@router.get("/evaluations/{evaluation_id}/results")
async def extraction_tab(
    evaluation_id: str,
    service: ResultsServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    sort_key: str = "name",
    sort_dir: SortDir = SortDir.ASC,
    expanded_feature_id: str | None = None,
    by_language_feature_id: str | None = None,
    by_language_model_id: str | None = None,
) -> ExtractionTabResponse:
    """Tab 1.

    **An unscored run is 200 with `scored: false`, never a 404.** The UI
    renders a state, and an error status would force exactly the toast the
    design rejects — the same reasoning §15.5 applied to an unreachable
    endpoint.
    """
    try:
        view = await service.extraction_tab(
            EvaluationId(evaluation_id),
            page=page,
            page_size=page_size,
            sort_key=sort_key,
            sort_dir=sort_dir,
            expanded_feature_id=FeatureId(expanded_feature_id) if expanded_feature_id else None,
            by_language_feature_id=(
                FeatureId(by_language_feature_id) if by_language_feature_id else None
            ),
            by_language_model_id=by_language_model_id,
        )
        statuses = await service.scoring_status(EvaluationId(evaluation_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _extraction_tab(view, scored=any(s.is_scored for s in statuses))


@router.get("/evaluations/{evaluation_id}/results/{feature_id}/breakdown")
async def breakdown(
    evaluation_id: str, feature_id: str, service: ResultsServiceDep
) -> BreakdownResponse:
    try:
        statuses = await service.scoring_status(EvaluationId(evaluation_id))
        view = await service.breakdown(
            tuple(RunId(s.run_id) for s in statuses), FeatureId(feature_id)
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _breakdown(view)


@router.get("/evaluations/{evaluation_id}/results/{feature_id}/by-language")
async def by_language(
    evaluation_id: str, feature_id: str, model_id: str, service: ResultsServiceDep
) -> ByLanguageResponse:
    try:
        view = await service.by_language(RunId(model_id), FeatureId(feature_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _by_language(view)


@router.post("/runs/{run_id}/rescore", status_code=status.HTTP_202_ACCEPTED)
async def rescore(run_id: str, service: ScoringServiceDep) -> TaskAcceptedResponse:
    """Re-score one run, **preserving analyst tags** (SD21).

    409 for a `failed` or `interrupted` run: a partial corpus produces
    real-looking numbers over an unstated denominator.
    """
    # **`202 Accepted` now means it.** This awaited the whole pass and then
    # answered with `task_id=run_id` — a status code describing work that had
    # already finished, and an id that `GET /api/v1/tasks/{id}` answers 404
    # for. `submit_rescore` raises both refusals before scheduling anything,
    # so the status codes are unchanged; the id is now one the caller can
    # poll, which is what the response model has always claimed it was.
    #
    # The docstring above is deliberately untouched: it *is* the endpoint's
    # public description (`tests/api/openapi_snapshot.json`), and nothing
    # about the wire contract changed — only whether the app keeps its side
    # of it. History belongs here, not in the published schema.
    try:
        task_id = await service.submit_rescore(RunId(run_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except RunNotScoreableError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return TaskAcceptedResponse(task_id=str(task_id))
