# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/evaluations` — drafts, edits and the launch commit
(plan-phase-3.md §9, sw-design.md §15.2).

Launching with an **unfrozen** feature config is 422 and creates nothing;
editing a **launched** evaluation is 409. Both are the service's errors
translated, not this router's own judgement. Thin translation only — same
idiom as `features.py`/`codelists.py` (F1/F2, phase 2): small
`_xxx_response(view) -> XxxResponse` mapping functions, `_not_found`/
`_locked`, and a `JSONResponse` built directly for the 422 case so the error
body's fields are top-level, not nested under `"detail"`.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import EvaluationServiceDep, LifecycleServiceDep, RunServiceDep
from ra2.api.schemas import (
    ConnectionResponse,
    CreateEvaluationRequest,
    DiscardPreview,
    DiscardResponse,
    ErrorResponse,
    EvaluationDraftResponse,
    EvaluationLaunchResponse,
    EvaluationResponse,
    FeatureValidationErrorResponse,
    ModelChoiceResponse,
    PageMeta,
    ProvenanceResponse,
    RunPage,
    RunProgressResponse,
    RunResponse,
    UpdateEvaluationRequest,
)
from ra2.api.v1.discard import conflict, discard_response
from ra2.api.v1.discard import discard_preview as to_preview
from ra2.domain.ids import CorpusId, EvaluationId, FeatureConfigId, PromptTemplateId
from ra2.services.errors import (
    EvaluationLockedError,
    FeatureValidationError,
    NotFoundError,
    RunActiveError,
    TaggedWorkPresentError,
)
from ra2.services.readmodels import (
    ConnectionView,
    EvaluationDraftView,
    EvaluationView,
    ModelChoiceView,
    Page,
    ProvenanceView,
    RunProgressView,
    RunView,
)

__all__ = ["router"]

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _draft_response(view: EvaluationDraftView) -> EvaluationDraftResponse:
    return EvaluationDraftResponse(
        evaluation_id=view.evaluation_id,
        name=view.name,
        corpus_id=view.corpus_id,
        feature_config_id=view.feature_config_id,
        prompt_template_id=view.prompt_template_id,
        prompt_language=view.prompt_language,
        temperature=view.temperature,
        seed=view.seed,
        reasoning_effort=view.reasoning_effort,
        size=view.size,
        selected_models=list(view.selected_models),
        launched_at=view.launched_at,
    )


def _connection_response(view: ConnectionView) -> ConnectionResponse:
    return ConnectionResponse(
        endpoint=view.endpoint,
        status=view.status,
        reachable=view.is_reachable,
        timeout_s=view.timeout_s,
        reason=view.reason,
        gpu_name=view.gpu_name,
        gpu_vram_bytes=view.gpu_vram_bytes,
    )


def _model_choice_response(view: ModelChoiceView) -> ModelChoiceResponse:
    return ModelChoiceResponse(
        tag=view.tag,
        digest=view.digest,
        size_bytes=view.size_bytes,
        fits_vram=view.fits_vram,
        selected=view.selected,
    )


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


def _run_page_response(page: Page[RunView] | None) -> RunPage | None:
    if page is None:
        return None
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


def _provenance_response(view: ProvenanceView | None) -> ProvenanceResponse | None:
    if view is None:
        return None
    return ProvenanceResponse(
        model_name=view.model_name,
        model_digest=view.model_digest,
        prompt_template_version=view.prompt_template_version,
        prompt_template_fingerprint=view.prompt_template_fingerprint,
        temperature=view.temperature,
        seed=view.seed,
        feature_config_id=view.feature_config_id,
        feature_fingerprints=dict(view.feature_fingerprints),
        corpus_id=view.corpus_id,
        corpus_version=view.corpus_version,
        host_platform=view.host_platform,
        gpu_name=view.gpu_name,
        llm_endpoint=view.llm_endpoint,
        llm_reasoning_effort=view.llm_reasoning_effort,
    )


def _evaluation_response(view: EvaluationView) -> EvaluationResponse:
    return EvaluationResponse(
        draft=_draft_response(view.draft),
        connection=_connection_response(view.connection),
        models=[_model_choice_response(m) for m in view.models],
        progress=[_run_progress_response(p) for p in view.progress],
        runs=_run_page_response(view.runs),
        provenance=_provenance_response(view.provenance),
        feature_config_label=view.feature_config_label,
        corpus_label=view.corpus_label,
        corpus_record_count=view.corpus_record_count,
        dev_record_max=view.dev_record_max,
        can_launch=view.can_launch,
    )


# ---------------------------------------------------------------------------
# error builders
# ---------------------------------------------------------------------------


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _locked(exc: EvaluationLockedError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _validation_error_response(exc: FeatureValidationError) -> JSONResponse:
    """422, body **is** `FeatureValidationErrorResponse` — nothing was
    created (or changed). Same top-level-fields contract as `features.py`'s
    `_validation_error_response`: a plain `HTTPException` would nest this
    under `"detail"`, which is not what the schema promises."""
    body = FeatureValidationErrorResponse(validation_errors=list(exc.validation_errors))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[EvaluationDraftResponse])
async def list_evaluations(service: EvaluationServiceDep) -> list[EvaluationDraftResponse]:
    views = await service.list_evaluations()
    return [_draft_response(v) for v in views]


@router.post("", response_model=EvaluationDraftResponse, status_code=status.HTTP_201_CREATED)
async def save_draft(
    body: CreateEvaluationRequest, service: EvaluationServiceDep
) -> EvaluationDraftResponse:
    """ "Save draft" — the row exists before the inputs are final."""
    try:
        view = await service.save_draft(
            name=body.name,
            corpus_id=CorpusId(body.corpus_id),
            feature_config_id=FeatureConfigId(body.feature_config_id),
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _draft_response(view)


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(evaluation_id: str, service: EvaluationServiceDep) -> EvaluationResponse:
    """One whole Evaluation screen: setup, models, connection, progress, runs
    and provenance."""
    try:
        view = await service.get(EvaluationId(evaluation_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _evaluation_response(view)


@router.put(
    "/{evaluation_id}",
    response_model=EvaluationDraftResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": FeatureValidationErrorResponse}},
)
async def update_draft(
    evaluation_id: str, body: UpdateEvaluationRequest, service: EvaluationServiceDep
) -> EvaluationDraftResponse | JSONResponse:
    """409 once `launched_at` is set — an evaluation is immutable after. 422
    when the edit selects a model the host is known not to have the VRAM
    for."""
    try:
        view = await service.update_draft(
            EvaluationId(evaluation_id),
            name=body.name,
            corpus_id=None if body.corpus_id is None else CorpusId(body.corpus_id),
            feature_config_id=(
                None if body.feature_config_id is None else FeatureConfigId(body.feature_config_id)
            ),
            prompt_template_id=(
                None
                if body.prompt_template_id is None
                else PromptTemplateId(body.prompt_template_id)
            ),
            prompt_language=body.prompt_language,
            temperature=body.temperature,
            seed=body.seed,
            reasoning_effort=body.reasoning_effort,
            size=body.size,
            selected_models=(None if body.selected_models is None else tuple(body.selected_models)),
        )
    except EvaluationLockedError as exc:
        raise _locked(exc) from exc
    except FeatureValidationError as exc:
        return _validation_error_response(exc)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _draft_response(view)


@router.post(
    "/{evaluation_id}/launch",
    response_model=EvaluationLaunchResponse,
    responses={422: {"model": FeatureValidationErrorResponse}, 409: {"model": ErrorResponse}},
)
async def launch(
    evaluation_id: str,
    service: EvaluationServiceDep,
    runs: RunServiceDep,
) -> EvaluationLaunchResponse | JSONResponse:
    """Pin the inputs, snapshot the codelists and fingerprints, create one
    `queued` run per selected model — then submit the worker.

    The snapshot and the runs land in **one transaction**
    (`EvaluationService.launch`); submitting the work is a second step, so a
    failed submit cannot leave a half-pinned evaluation. The returned
    `evaluation` reflects the state right after that transaction commits —
    not after the (possibly already-finished, on a synchronous task runner)
    work — the UI polls `task_id` for progress.
    """
    eval_id = EvaluationId(evaluation_id)
    try:
        view = await service.launch(eval_id)
    except FeatureValidationError as exc:
        return _validation_error_response(exc)
    except EvaluationLockedError as exc:
        raise _locked(exc) from exc
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    task_id = await runs.launch_runs(eval_id)
    return EvaluationLaunchResponse(evaluation=_evaluation_response(view), task_id=str(task_id))


# ---------------------------------------------------------------------------
# discard — sw-design.md §18
# ---------------------------------------------------------------------------


@router.get("/{evaluation_id}/discard-preview", response_model=DiscardPreview)
async def discard_preview(evaluation_id: str, service: LifecycleServiceDep) -> DiscardPreview:
    """The counts summed over this evaluation's runs. Writes nothing."""
    try:
        view = await service.evaluation_preview(EvaluationId(evaluation_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return to_preview(view)


@router.delete(
    "/{evaluation_id}",
    response_model=DiscardResponse,
    responses={409: {"model": ErrorResponse}},
)
async def discard_evaluation(
    evaluation_id: str, service: LifecycleServiceDep, force: bool = False
) -> DiscardResponse:
    """Discard an evaluation and its runs (§18.1).

    **The corpus, the feature config and the prompt versions it cites are
    untouched** — they are `RESTRICT`, and discarding an evaluation is not a
    way to delete a corpus.

    409 when any run is `queued` or `running` (G1), and when tagged mismatches
    would be destroyed without `force` (G2).
    """
    key = EvaluationId(evaluation_id)
    try:
        before = await service.evaluation_preview(key)
        await service.discard_evaluation(key, force=force)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except (RunActiveError, TaggedWorkPresentError) as exc:
        raise conflict(exc) from exc
    return discard_response(before, forced=force and before.tagged_mismatches > 0)
