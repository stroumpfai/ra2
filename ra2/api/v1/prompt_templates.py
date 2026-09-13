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
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import PromptServiceDep
from ra2.api.schemas import (
    CreatePromptTemplateRequest,
    PromptTemplateResponse,
    PromptValidationErrorResponse,
    ResolvedPromptResponse,
    ResolvePromptRequest,
    SlotResponse,
)

__all__ = ["router"]

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

_NOT_BUILT = "not implemented until Wave 3 (K1)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=list[PromptTemplateResponse])
async def list_versions(service: PromptServiceDep) -> list[PromptTemplateResponse]:
    """Every version, newest first, each with its citation count."""
    raise _todo()


@router.get("/slots", response_model=list[SlotResponse])
async def list_slots(service: PromptServiceDep) -> list[SlotResponse]:
    """The closed slot catalogue (`domain.prompt.SLOTS`)."""
    raise _todo()


@router.post(
    "",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": PromptValidationErrorResponse}},
)
async def save_as_next_version(
    body: CreatePromptTemplateRequest, service: PromptServiceDep
) -> PromptTemplateResponse:
    """ "Save as vN" — copy-on-write. Never mutates an existing version."""
    raise _todo()


@router.post("/resolve", response_model=ResolvedPromptResponse)
async def resolve(body: ResolvePromptRequest, service: PromptServiceDep) -> ResolvedPromptResponse:
    """Expand a template against a feature set and one record.

    **No model call** (plan-phase-3.md C4). Both preview buttons land here.
    """
    raise _todo()


@router.get("/{prompt_template_id}", response_model=PromptTemplateResponse)
async def get_version(prompt_template_id: str, service: PromptServiceDep) -> PromptTemplateResponse:
    raise _todo()


@router.post("/{prompt_template_id}/activate", response_model=PromptTemplateResponse)
async def activate(prompt_template_id: str, service: PromptServiceDep) -> PromptTemplateResponse:
    """Mark the version new evaluations default to. Exactly one at a time."""
    raise _todo()


@router.delete("/{prompt_template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(prompt_template_id: str, service: PromptServiceDep) -> None:
    """409 when any run cites it; nothing is deleted."""
    raise _todo()
