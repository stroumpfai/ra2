# STUB — bodies owned by F1 (feat/p2-api-codelists). Not frozen.
"""`/api/v1/codelists` — upload, list columns with status, map/unmap, list
attributes (sw-design.md §14, plan-phase-2.md §9).

A malformed upload returns 422 with the validation errors, not a 500; a
re-upload of an unchanged file returns 200 with `no_change: true`.
"""

from fastapi import APIRouter, HTTPException, UploadFile, status

from ra2.api.deps import CodelistServiceDep
from ra2.api.schemas import (
    CodeAttributeResponse,
    CodelistImportErrorResponse,
    CodelistImportResponse,
    ColumnMappingResponse,
    MapColumnRequest,
)

__all__ = ["router"]

router = APIRouter(prefix="/codelists", tags=["codelists"])

_NOT_BUILT = "not implemented until Wave 3 (F1)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.post(
    "/import",
    response_model=CodelistImportResponse,
    responses={422: {"model": CodelistImportErrorResponse}},
)
async def import_codelist(file: UploadFile, service: CodelistServiceDep) -> CodelistImportResponse:
    """sw-design.md §14.1: fails whole, or writes whole. Never partial."""
    raise _todo()


@router.get("/attributes", response_model=list[CodeAttributeResponse])
async def list_attributes(service: CodelistServiceDep) -> list[CodeAttributeResponse]:
    raise _todo()


@router.get("/columns", response_model=list[ColumnMappingResponse])
async def list_columns(
    corpus_id: str, language: str, service: CodelistServiceDep
) -> list[ColumnMappingResponse]:
    raise _todo()


@router.put("/columns/mapping", response_model=ColumnMappingResponse)
async def map_column(body: MapColumnRequest, service: CodelistServiceDep) -> ColumnMappingResponse:
    raise _todo()


@router.delete("/columns/mapping", status_code=status.HTTP_204_NO_CONTENT)
async def unmap_column(corpus_id: str, source_column: str, service: CodelistServiceDep) -> None:
    raise _todo()
