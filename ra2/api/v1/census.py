# STUB — bodies owned by C2 (feat/m4-api-census). Not frozen.
"""`/api/v1/census` — columns with filter/sort/page, summary, CSV export."""

from fastapi import APIRouter, HTTPException, Response, status

from ra2.api.deps import CensusServiceDep, ExportServiceDep
from ra2.api.schemas import CensusPage, CensusSummaryResponse
from ra2.services.readmodels import SortDir

__all__ = ["router"]

router = APIRouter(prefix="/census", tags=["census"])

_NOT_BUILT = "not implemented until M4 (C2)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("/{corpus_id}/columns", response_model=CensusPage)
async def list_columns(
    corpus_id: str,
    service: CensusServiceDep,
    table_name: str | None = None,
    min_populated_rate: float | None = None,
    sort_key: str = "populated_rate",
    sort_dir: SortDir = SortDir.DESC,
    page: int = 1,
    page_size: int = 25,
) -> CensusPage:
    raise _todo()


@router.get("/{corpus_id}/summary", response_model=CensusSummaryResponse)
async def get_summary(corpus_id: str, service: CensusServiceDep) -> CensusSummaryResponse:
    """The population-profile buckets and the per-table column counts."""
    raise _todo()


@router.get("/{corpus_id}/export.csv")
async def export_csv(
    corpus_id: str,
    service: ExportServiceDep,
    table_name: str | None = None,
    min_populated_rate: float | None = None,
    sort_key: str = "populated_rate",
    sort_dir: SortDir = SortDir.DESC,
) -> Response:
    """UTF-8 **with BOM**, `;`-delimited, current filter and sort only."""
    raise _todo()
