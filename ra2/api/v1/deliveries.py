# STUB — bodies owned by C1 (feat/m4-api-deliveries). Not frozen.
"""`/api/v1/deliveries` — register, list, analyse, override + re-parse, select.

Every handler returns 501 at M0. The routes exist so the shape is settled and
`create_app()` is final.
"""

from fastapi import APIRouter, HTTPException, UploadFile, status

from ra2.api.deps import DeliveryServiceDep
from ra2.api.schemas import (
    AnalyseResponse,
    DeliveryFileResponse,
    DeliveryResponse,
    FileOverrideRequest,
    RegisterDeliveryRequest,
    SelectFileRequest,
)

__all__ = ["router"]

router = APIRouter(prefix="/deliveries", tags=["deliveries"])

_NOT_BUILT = "not implemented until M4 (C1)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=list[DeliveryResponse])
async def list_deliveries(service: DeliveryServiceDep) -> list[DeliveryResponse]:
    raise _todo()


@router.post("", response_model=DeliveryResponse, status_code=status.HTTP_201_CREATED)
async def register_delivery(
    body: RegisterDeliveryRequest, service: DeliveryServiceDep
) -> DeliveryResponse:
    raise _todo()


@router.get("/{delivery_id}", response_model=DeliveryResponse)
async def get_delivery(delivery_id: str, service: DeliveryServiceDep) -> DeliveryResponse:
    raise _todo()


@router.post("/{delivery_id}/files", response_model=DeliveryFileResponse)
async def upload_file(
    delivery_id: str, file: UploadFile, service: DeliveryServiceDep
) -> DeliveryFileResponse:
    raise _todo()


@router.post("/{delivery_id}/analyse", response_model=AnalyseResponse)
async def analyse_delivery(delivery_id: str, service: DeliveryServiceDep) -> AnalyseResponse:
    raise _todo()


@router.patch("/{delivery_id}/files/{file_id}", response_model=DeliveryFileResponse)
async def override_and_reparse(
    delivery_id: str,
    file_id: str,
    body: FileOverrideRequest,
    service: DeliveryServiceDep,
) -> DeliveryFileResponse:
    """Re-runs analysis for this file alone (sw-design.md §6.2.5)."""
    raise _todo()


@router.put("/{delivery_id}/files/{file_id}/selection", response_model=DeliveryResponse)
async def set_file_selection(
    delivery_id: str,
    file_id: str,
    body: SelectFileRequest,
    service: DeliveryServiceDep,
) -> DeliveryResponse:
    """Returns the whole delivery so both counts recompute from one call."""
    raise _todo()


@router.delete("/{delivery_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file(delivery_id: str, file_id: str, service: DeliveryServiceDep) -> None:
    raise _todo()
