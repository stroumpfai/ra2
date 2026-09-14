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

from fastapi import APIRouter

from ra2.api.deps import EvaluationServiceDep
from ra2.api.schemas import (
    ConnectionProbeResponse,
    ConnectionResponse,
    ModelCatalogResponse,
    ModelChoiceResponse,
    TestConnectionRequest,
)
from ra2.services.readmodels import ConnectionView, ModelChoiceView

__all__ = ["router"]

router = APIRouter(prefix="/models", tags=["models"])


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


@router.get("", response_model=ModelCatalogResponse)
async def list_models(service: EvaluationServiceDep, refresh: bool = False) -> ModelCatalogResponse:
    """Tag, digest, size and `fits_vram` per model, plus the connection line.

    `refresh` is the settings dialog's "refresh model list" — there is no
    cache to bypass here (`connection_status()`/`list_models()` always ask
    the catalogue fresh), so the parameter exists for the UI's intent and the
    OpenAPI contract rather than to select a different code path: reachability
    is re-checked on **every** call, on view load and on that press, **never
    on a timer** (plan-phase-3.md C3).
    """
    connection = await service.connection_status()
    choices = await service.list_models()
    return ModelCatalogResponse(
        connection=_connection_response(connection),
        models=[_model_choice_response(m) for m in choices],
    )


@router.post("/test", response_model=ConnectionProbeResponse)
async def test_connection(
    request: TestConnectionRequest, service: EvaluationServiceDep
) -> ConnectionProbeResponse:
    """Probe an endpoint that is **not** the configured one, and name the cause.

    The settings dialog's "Test connection": you type a URL, press it, and
    find out whether Ollama is there *before* putting the value in `.env`.
    Nothing is persisted — `RA2_LLM_BASE_URL` remains the only source of the
    endpoint the app actually uses, so this route changes no state and is a
    `POST` only because the endpoint travels in a body.

    **Always 200**, including for a host that is not loopback: that refusal is
    the most useful answer this route gives, and a 4xx would make the UI
    render it as a failure of the request rather than a fact about the URL. It
    is settled before any socket is opened (N1, §15 F4).
    """
    view = await service.test_connection(request.endpoint, request.timeout_s)
    return ConnectionProbeResponse(
        endpoint=view.endpoint,
        code=view.code,
        ok=view.ok,
        detail=view.detail,
        latency_ms=view.latency_ms,
        model_count=view.model_count,
        http_status=view.http_status,
        probe_timeout_s=view.probe_timeout_s,
    )
