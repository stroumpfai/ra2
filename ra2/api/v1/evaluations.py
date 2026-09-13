# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/evaluations` — drafts, edits and the launch commit
(plan-phase-3.md §9, sw-design.md §15.2).

Launching with an **unfrozen** feature config is 422 and creates nothing;
editing a **launched** evaluation is 409. Both are the service's errors
translated, not this router's own judgement.
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import EvaluationServiceDep, RunServiceDep
from ra2.api.schemas import (
    CreateEvaluationRequest,
    EvaluationDraftResponse,
    EvaluationLaunchResponse,
    EvaluationResponse,
    FeatureValidationErrorResponse,
    UpdateEvaluationRequest,
)

__all__ = ["router"]

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

_NOT_BUILT = "not implemented until Wave 3 (K2)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=list[EvaluationDraftResponse])
async def list_evaluations(service: EvaluationServiceDep) -> list[EvaluationDraftResponse]:
    raise _todo()


@router.post("", response_model=EvaluationDraftResponse, status_code=status.HTTP_201_CREATED)
async def save_draft(
    body: CreateEvaluationRequest, service: EvaluationServiceDep
) -> EvaluationDraftResponse:
    """ "Save draft" — the row exists before the inputs are final."""
    raise _todo()


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(evaluation_id: str, service: EvaluationServiceDep) -> EvaluationResponse:
    """One whole Evaluation screen: setup, models, connection, progress, runs
    and provenance."""
    raise _todo()


@router.put("/{evaluation_id}", response_model=EvaluationDraftResponse)
async def update_draft(
    evaluation_id: str, body: UpdateEvaluationRequest, service: EvaluationServiceDep
) -> EvaluationDraftResponse:
    """409 once `launched_at` is set — an evaluation is immutable after."""
    raise _todo()


@router.post(
    "/{evaluation_id}/launch",
    response_model=EvaluationLaunchResponse,
    responses={422: {"model": FeatureValidationErrorResponse}},
)
async def launch(
    evaluation_id: str,
    service: EvaluationServiceDep,
    runs: RunServiceDep,
) -> EvaluationLaunchResponse:
    """Pin the inputs, snapshot the codelists and fingerprints, create one
    `queued` run per selected model — then submit the worker.

    The snapshot and the runs land in **one transaction**
    (`EvaluationService.launch`); submitting the work is a second step, so a
    failed submit cannot leave a half-pinned evaluation.
    """
    raise _todo()
