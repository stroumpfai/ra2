# STUB — bodies owned by C2 (feat/m4-api-census). Not frozen.
"""`/api/v1/census` — columns with filter/sort/page, summary, CSV export."""

from fastapi import APIRouter, Response

from ra2.api.deps import CensusServiceDep, ExportServiceDep
from ra2.api.schemas import (
    CensusColumnResponse,
    CensusPage,
    CensusSummaryResponse,
    PageMeta,
    ProfileBucketResponse,
    ValueCountResponse,
)
from ra2.domain.ids import CorpusId
from ra2.services.readmodels import CensusColumnView, CensusSummary, Page, SortDir

__all__ = ["router"]

router = APIRouter(prefix="/census", tags=["census"])


def _to_column_response(view: CensusColumnView) -> CensusColumnResponse:
    """Field-by-field: no ORM object, no recomputation (sw-design.md §7)."""
    return CensusColumnResponse(
        census_column_id=view.census_column_id,
        table_name=view.table_name,
        column_name=view.column_name,
        type_hint=view.type_hint,
        record_count=view.record_count,
        populated_count=view.populated_count,
        populated_rate=view.populated_rate,
        distinct_count=view.distinct_count,
        top_value_share=view.top_value_share,
        long_tail=view.long_tail,
        top_values=[
            ValueCountResponse(value_raw=v.value_raw, count=v.count, share=v.share)
            for v in view.top_values
        ],
        in_config=view.in_config,
    )


def _to_page_response(page: Page[CensusColumnView]) -> CensusPage:
    return CensusPage(
        items=[_to_column_response(item) for item in page.items],
        meta=PageMeta(
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            sort_key=page.sort_key,
            sort_dir=page.sort_dir,
        ),
    )


def _to_summary_response(summary: CensusSummary) -> CensusSummaryResponse:
    return CensusSummaryResponse(
        corpus_id=summary.corpus_id,
        buckets=[
            ProfileBucketResponse(label=bucket.label, column_count=bucket.column_count)
            for bucket in summary.buckets
        ],
        column_counts_by_table=dict(summary.column_counts_by_table),
        total_column_count=summary.total_column_count,
    )


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
    result = await service.columns(
        CorpusId(corpus_id),
        table_name=table_name,
        min_populated_rate=min_populated_rate,
        sort_key=sort_key,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return _to_page_response(result)


@router.get("/{corpus_id}/summary", response_model=CensusSummaryResponse)
async def get_summary(corpus_id: str, service: CensusServiceDep) -> CensusSummaryResponse:
    """The population-profile buckets and the per-table column counts."""
    summary = await service.summary(CorpusId(corpus_id))
    return _to_summary_response(summary)


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
    csv_bytes = await service.census_csv(
        CorpusId(corpus_id),
        table_name=table_name,
        min_populated_rate=min_populated_rate,
        sort_key=sort_key,
        sort_dir=sort_dir,
    )
    return Response(content=csv_bytes, media_type="text/csv")
