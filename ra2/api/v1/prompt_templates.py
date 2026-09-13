# STUB — bodies owned by K1 (feat/p3-api-prompts). Not frozen.
"""`/api/v1/prompt-templates` — versions, copy-on-write saves, the active
flag, deletes, and the no-model-call resolve (plan-phase-3.md §9).

**There is deliberately no `PATCH` route**, and there never will be: saving is
an `INSERT` at `version + 1` and a cited version's `source` stays
byte-identical, because the runs citing it must keep resolving to the exact
text they used (sw-design.md §15.1). K1's exit criteria assert the absence —
it is the contract, not an oversight.

An invalid template is **422 with the typed validation errors**, not a 500.
Deleting a cited version is **409**.

Thin translation only — same idiom as `codelists.py`/`features.py` (phase 2):
small `_xxx_response(view) -> XxxResponse` mapping functions, `_not_found`,
and a `JSONResponse` built directly for the 422 case so the error body's
fields are top-level, not nested under `"detail"`.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import PromptServiceDep
from ra2.api.schemas import (
    CreatePromptTemplateRequest,
    PromptTemplateResponse,
    PromptValidationErrorResponse,
    PromptValidationIssueResponse,
    ResolvedPromptResponse,
    ResolvePromptRequest,
    SlotResponse,
)
from ra2.domain.ids import FeatureConfigId, PromptTemplateId, RecordId
from ra2.domain.prompt import PromptValidationError
from ra2.services.errors import NotFoundError, PromptTemplateCitedError, PromptTemplateInvalidError
from ra2.services.readmodels import PromptTemplateView, ResolvedPromptView, SlotView

__all__ = ["router"]

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _template_response(view: PromptTemplateView) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        prompt_template_id=view.prompt_template_id,
        version=view.version,
        source=view.source,
        created_at=view.created_at,
        is_active=view.is_active,
        cited_by_run_count=view.cited_by_run_count,
        fingerprint=view.fingerprint,
        deletable=view.deletable,
    )


def _slot_response(view: SlotView) -> SlotResponse:
    return SlotResponse(
        name=view.name, token=view.token, required=view.required, resolves_to=view.resolves_to
    )


def _validation_issue_response(error: PromptValidationError) -> PromptValidationIssueResponse:
    return PromptValidationIssueResponse(code=error.code, slot=error.slot, offset=error.offset)


def _resolved_response(view: ResolvedPromptView) -> ResolvedPromptResponse:
    return ResolvedPromptResponse(
        text=view.text,
        token_estimate=view.token_estimate,
        record_key=view.record_key,
        feature_count=view.feature_count,
        slots_used=list(view.slots_used),
        validation_errors=[_validation_issue_response(e) for e in view.validation_errors],
    )


# ---------------------------------------------------------------------------
# error builders
# ---------------------------------------------------------------------------


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: PromptTemplateCitedError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _invalid_response(exc: PromptTemplateInvalidError) -> JSONResponse:
    """422, body **is** `PromptValidationErrorResponse` — nothing was saved
    (sw-design.md §15.1). Same top-level-fields contract as `features.py`'s
    `_validation_error_response`: a plain `HTTPException` would nest this
    under `"detail"`, which is not what the schema promises."""
    body = PromptValidationErrorResponse(
        validation_errors=[_validation_issue_response(e) for e in exc.validation_errors]
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PromptTemplateResponse])
async def list_versions(service: PromptServiceDep) -> list[PromptTemplateResponse]:
    """Every version, newest first, each with its citation count."""
    views = await service.list_versions()
    return [_template_response(v) for v in views]


@router.get("/slots", response_model=list[SlotResponse])
async def list_slots(service: PromptServiceDep) -> list[SlotResponse]:
    """The closed slot catalogue (`domain.prompt.SLOTS`)."""
    views = await service.slots()
    return [_slot_response(v) for v in views]


@router.post(
    "",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": PromptValidationErrorResponse}},
)
async def save_as_next_version(
    body: CreatePromptTemplateRequest, service: PromptServiceDep
) -> PromptTemplateResponse | JSONResponse:
    """ "Save as vN" — copy-on-write. Never mutates an existing version."""
    try:
        view = await service.save_as_next_version(body.source)
    except PromptTemplateInvalidError as exc:
        return _invalid_response(exc)
    return _template_response(view)


@router.post("/resolve", response_model=ResolvedPromptResponse)
async def resolve(body: ResolvePromptRequest, service: PromptServiceDep) -> ResolvedPromptResponse:
    """Expand a template against a feature set and one record.

    **No model call** (plan-phase-3.md C4). Both preview buttons land here.
    """
    try:
        view = await service.preview(
            PromptTemplateId(body.prompt_template_id),
            FeatureConfigId(body.feature_config_id),
            RecordId(body.record_id),
            language=body.language,
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _resolved_response(view)


@router.get("/{prompt_template_id}", response_model=PromptTemplateResponse)
async def get_version(prompt_template_id: str, service: PromptServiceDep) -> PromptTemplateResponse:
    try:
        view = await service.get(PromptTemplateId(prompt_template_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _template_response(view)


@router.post("/{prompt_template_id}/activate", response_model=PromptTemplateResponse)
async def activate(prompt_template_id: str, service: PromptServiceDep) -> PromptTemplateResponse:
    """Mark the version new evaluations default to. Exactly one at a time."""
    try:
        view = await service.activate(PromptTemplateId(prompt_template_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _template_response(view)


@router.delete("/{prompt_template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(prompt_template_id: str, service: PromptServiceDep) -> None:
    """409 when any run cites it; nothing is deleted."""
    try:
        await service.delete(PromptTemplateId(prompt_template_id))
    except PromptTemplateCitedError as exc:
        raise _conflict(exc) from exc
    except NotFoundError as exc:
        raise _not_found(exc) from exc
