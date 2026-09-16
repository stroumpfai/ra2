# STUB — bodies owned by C1 (feat/m4-api-deliveries). Not frozen.
"""`/api/v1/deliveries` — register, list, analyse, override + re-parse, select.

Thin translation only (plan-m0-m5.md §7): every handler calls `DeliveryService`
and maps its read models (`ra2.services.readmodels`) field-by-field onto the
wire schemas (`ra2.api.schemas`). No business logic, no ORM object crosses
this boundary.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from ra2.api.deps import DeliveryServiceDep, LifecycleServiceDep
from ra2.api.schemas import (
    AnalyseResponse,
    DeliveryFileResponse,
    DeliveryResponse,
    DiscardPreview,
    DiscardResponse,
    ErrorResponse,
    FileOverrideRequest,
    FindingResponse,
    RegisterDeliveryRequest,
    SelectFileRequest,
)
from ra2.api.v1.discard import conflict, discard_response
from ra2.api.v1.discard import discard_preview as to_preview
from ra2.domain.findings import Finding
from ra2.domain.ids import DeliveryId, FileId
from ra2.services.errors import DeliveryCitedError, NotFoundError
from ra2.services.readmodels import DeliveryFileView, DeliveryView

__all__ = ["router"]

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _finding_response(finding: Finding) -> FindingResponse:
    return FindingResponse(
        code=finding.code,
        severity=finding.severity,
        file_id=finding.file_id,
        key=finding.key,
        line_no=finding.line_no,
        detail=dict(finding.detail),
    )


def _file_response(view: DeliveryFileView) -> DeliveryFileResponse:
    return DeliveryFileResponse(
        file_id=view.file_id,
        filename=view.filename,
        relative_path=view.relative_path,
        byte_size=view.byte_size,
        sha256=view.sha256,
        file_kind=view.file_kind,
        set_key=view.set_key,
        canton=view.canton,
        encoding=view.encoding,
        encoding_detected=view.encoding_detected,
        delimiter=view.delimiter,
        quote_char=view.quote_char,
        row_count=view.row_count,
        ok_count=view.ok_count,
        recovered_count=view.recovered_count,
        rejected_count=view.rejected_count,
        header_ok=view.header_ok,
        selected=view.selected,
        analysed_at=view.analysed_at,
        findings=[_finding_response(f) for f in view.findings],
    )


def _delivery_response(view: DeliveryView) -> DeliveryResponse:
    return DeliveryResponse(
        delivery_id=view.delivery_id,
        name=view.name,
        source_kind=view.source_kind,
        root_path=view.root_path,
        status=view.status,
        created_at=view.created_at,
        analysed_at=view.analysed_at,
        files=[_file_response(f) for f in view.files],
        # A computed `@property`, already correct (sw-design.md §8.1).
        selected_record_count=view.selected_record_count,
    )


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[DeliveryResponse])
async def list_deliveries(service: DeliveryServiceDep) -> list[DeliveryResponse]:
    views = await service.list_deliveries()
    return [_delivery_response(v) for v in views]


@router.post("", response_model=DeliveryResponse, status_code=status.HTTP_201_CREATED)
async def register_delivery(
    body: RegisterDeliveryRequest, service: DeliveryServiceDep
) -> DeliveryResponse:
    root_path = Path(body.root_path) if body.root_path is not None else None
    delivery_id = await service.register(
        body.name, source_kind=body.source_kind, root_path=root_path
    )
    view = await service.get(delivery_id)
    return _delivery_response(view)


@router.get("/{delivery_id}", response_model=DeliveryResponse)
async def get_delivery(delivery_id: str, service: DeliveryServiceDep) -> DeliveryResponse:
    try:
        view = await service.get(DeliveryId(delivery_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _delivery_response(view)


@router.post("/{delivery_id}/files", response_model=DeliveryFileResponse)
async def upload_file(
    delivery_id: str, file: UploadFile, service: DeliveryServiceDep
) -> DeliveryFileResponse:
    try:
        file_id = await service.add_file(DeliveryId(delivery_id), file.filename or "", file.file)
        view = await service.get(DeliveryId(delivery_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    file_view = next((f for f in view.files if f.file_id == file_id), None)
    if file_view is None:  # pragma: no cover - add_file always creates/updates the row
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="uploaded file missing from delivery view",
        )
    return _file_response(file_view)


@router.post("/{delivery_id}/analyse", response_model=AnalyseResponse)
async def analyse_delivery(delivery_id: str, service: DeliveryServiceDep) -> AnalyseResponse:
    try:
        task_id = await service.analyse(DeliveryId(delivery_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return AnalyseResponse(task_id=task_id)


@router.patch("/{delivery_id}/files/{file_id}", response_model=DeliveryFileResponse)
async def override_and_reparse(
    delivery_id: str,
    file_id: str,
    body: FileOverrideRequest,
    service: DeliveryServiceDep,
) -> DeliveryFileResponse:
    """Re-runs analysis for this file alone (sw-design.md §6.2.5)."""
    try:
        view = await service.reparse_file(
            DeliveryId(delivery_id),
            FileId(file_id),
            encoding=body.encoding,
            delimiter=body.delimiter,
            quote_char=body.quote_char,
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _file_response(view)


@router.put("/{delivery_id}/files/{file_id}/selection", response_model=DeliveryResponse)
async def set_file_selection(
    delivery_id: str,
    file_id: str,
    body: SelectFileRequest,
    service: DeliveryServiceDep,
) -> DeliveryResponse:
    """Returns the whole delivery so both counts recompute from one call."""
    try:
        view = await service.set_selected(
            DeliveryId(delivery_id), FileId(file_id), selected=body.selected
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _delivery_response(view)


@router.delete("/{delivery_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file(delivery_id: str, file_id: str, service: DeliveryServiceDep) -> None:
    try:
        await service.remove_file(DeliveryId(delivery_id), FileId(file_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc


# ---------------------------------------------------------------------------
# discard — sw-design.md §18
# ---------------------------------------------------------------------------


@router.get("/{delivery_id}/discard-preview", response_model=DiscardPreview)
async def discard_preview(delivery_id: str, service: LifecycleServiceDep) -> DiscardPreview:
    """How many files would go, and whether a corpus refuses the discard."""
    try:
        view = await service.delivery_preview(DeliveryId(delivery_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return to_preview(view)


@router.delete(
    "/{delivery_id}",
    response_model=DiscardResponse,
    responses={409: {"model": ErrorResponse}},
)
async def discard_delivery(delivery_id: str, service: LifecycleServiceDep) -> DiscardResponse:
    """Discard a delivery, its `delivery_file` rows and — for an **upload** —
    its stored bytes.

    A host-path delivery's files belong to the analyst and are left exactly
    where they are; only the rows go.

    409 when a corpus was frozen from it. There is no `force`: `corpus.
    delivery_id` is `SET NULL`, so forcing would silently null a provenance
    link rather than ask a question (§18.2).

    **No UI affordance corresponds to this route** (§18.6): the Import view
    shows one delivery and has no delivery list to hang a row action on. The
    analyst's equivalent is `just reset`.
    """
    key = DeliveryId(delivery_id)
    try:
        before = await service.delivery_preview(key)
        await service.discard_delivery(key)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except DeliveryCitedError as exc:
        raise conflict(exc) from exc
    return discard_response(before, forced=False)
