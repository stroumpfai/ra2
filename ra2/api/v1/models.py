# STUB — bodies owned by K2 (feat/p3-api-evaluations). Not frozen.
"""`/api/v1/models` — the endpoint's catalogue and its reachability
(plan-phase-3.md §9, sw-design.md §15.5).

**An unreachable endpoint returns 200 with `reachable: false`, never a 502.**
The UI renders the reason next to the endpoint line and disables Launch
(plan-phase-3.md C3); an error status would force exactly the toast the design
rejects.

The one exception is a `base_url` that is not loopback: `OllamaLLMClient`
refuses that at construction, so the app never starts with one and this route
never sees it (N1, §15 F4).
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import EvaluationServiceDep
from ra2.api.schemas import ModelCatalogResponse

__all__ = ["router"]

router = APIRouter(prefix="/models", tags=["models"])

_NOT_BUILT = "not implemented until Wave 3 (K2)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=ModelCatalogResponse)
async def list_models(service: EvaluationServiceDep, refresh: bool = False) -> ModelCatalogResponse:
    """Tag, digest, size and `fits_vram` per model, plus the connection line.

    `refresh` is the settings dialog's "refresh model list" — reachability is
    re-checked on view load and on that press, **never on a timer**.
    """
    raise _todo()
