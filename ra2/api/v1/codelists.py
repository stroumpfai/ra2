# STUB — bodies owned by F1 (feat/p2-api-codelists). Not frozen.
"""`/api/v1/codelists` — upload, list columns with status, map/unmap, list
attributes (sw-design.md §14, plan-phase-2.md §9).

A malformed upload returns 422 with the validation errors, not a 500; a
re-upload of an unchanged file returns 200 with `no_change: true`. Thin
translation only — same idiom as `corpora.py`/`deliveries.py` (C1, phase 1):
small `_xxx_response(view) -> XxxResponse` mapping functions, `_not_found`,
and a `JSONResponse` built directly for the 422 case so the error body's
fields are top-level, not nested under `"detail"`.

**No separate "get one attribute's code table" endpoint** (a question
plan-phase-2.md's prose left open for this router): `GET /codelists/columns`
already returns each column's `coverage.codes` — the full per-code usage
list (code, count, share, label, in_codelist) the design's edit zone codes
table (README §"Edit zone (right)") needs, once a corpus and column are
selected. Nothing in `design/code-feature/README.md` shows the codes table
rendered without that corpus/column context — the "Usage" column and the
"18 mapped" header line are both corpus-scoped counts, not codelist-only
ones — so a second endpoint would duplicate this one for no drawn case.
"""

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import CodelistServiceDep
from ra2.api.schemas import (
    CodeAttributeResponse,
    CodeImportErrorResponse,
    CodelistImportErrorResponse,
    CodelistImportResponse,
    CodeUsageResponse,
    ColumnCoverageResponse,
    ColumnMappingResponse,
    MapColumnRequest,
)
from ra2.domain.codelist_coverage import CodeUsage, ColumnCoverage
from ra2.domain.codes import CodeImportError
from ra2.domain.ids import CodeAttributeId, CorpusId
from ra2.services.errors import CodelistImportError, NotFoundError
from ra2.services.readmodels import CodeAttributeView, CodelistImportResult, ColumnMappingView

__all__ = ["router"]

router = APIRouter(prefix="/codelists", tags=["codelists"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _code_import_error_response(error: CodeImportError) -> CodeImportErrorResponse:
    return CodeImportErrorResponse(
        attribute_key=error.attribute_key, path=error.path, message=error.message
    )


def _import_result_response(result: CodelistImportResult) -> CodelistImportResponse:
    return CodelistImportResponse(
        code_table_import_id=result.code_table_import_id,
        source_hash=result.source_hash,
        imported_at=result.imported_at,
        attribute_count=result.attribute_count,
        no_change=result.no_change,
    )


def _attribute_response(view: CodeAttributeView) -> CodeAttributeResponse:
    return CodeAttributeResponse(
        code_attribute_id=view.code_attribute_id,
        key=view.key,
        chapter=view.chapter,
        name=dict(view.name),
        code_count=view.code_count,
    )


def _code_usage_response(usage: CodeUsage) -> CodeUsageResponse:
    return CodeUsageResponse(
        code=usage.code,
        count=usage.count,
        share=usage.share,
        label=usage.label,
        in_codelist=usage.in_codelist,
    )


def _coverage_response(coverage: ColumnCoverage) -> ColumnCoverageResponse:
    return ColumnCoverageResponse(
        status=coverage.status.value,
        language=coverage.language,
        codes=[_code_usage_response(c) for c in coverage.codes],
        labelled_count=coverage.labelled_count,
        total_count=coverage.total_count,
        coverage_pct=coverage.coverage_pct,
    )


def _column_response(view: ColumnMappingView) -> ColumnMappingResponse:
    return ColumnMappingResponse(
        corpus_id=view.corpus_id,
        table_name=view.table_name,
        column_name=view.column_name,
        distinct_in_corpus=view.distinct_in_corpus,
        mapping_id=view.mapping_id,
        mapped_attribute=(
            _attribute_response(view.mapped_attribute)
            if view.mapped_attribute is not None
            else None
        ),
        coverage=_coverage_response(view.coverage) if view.coverage is not None else None,
        used_by_features=list(view.used_by_features),
    )


def _codelist_import_error_response(exc: CodelistImportError) -> JSONResponse:
    """422, body **is** `CodelistImportErrorResponse` — nothing was imported
    (sw-design.md §14.1 step 1).

    Same "top-level fields, not nested under `detail`" contract as
    `corpora.py`'s `_blocking_findings_response`.
    """
    body = CodelistImportErrorResponse(
        import_errors=[_code_import_error_response(e) for e in exc.import_errors]
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.post(
    "/import",
    response_model=CodelistImportResponse,
    responses={422: {"model": CodelistImportErrorResponse}},
)
async def import_codelist(
    file: UploadFile, service: CodelistServiceDep
) -> CodelistImportResponse | JSONResponse:
    """sw-design.md §14.1: fails whole, or writes whole. Never partial."""
    content = await file.read()
    filename = file.filename or ""
    try:
        result = await service.import_file(filename, content)
    except CodelistImportError as exc:
        return _codelist_import_error_response(exc)
    return _import_result_response(result)


@router.get("/attributes", response_model=list[CodeAttributeResponse])
async def list_attributes(service: CodelistServiceDep) -> list[CodeAttributeResponse]:
    views = await service.list_attributes()
    return [_attribute_response(v) for v in views]


@router.get("/columns", response_model=list[ColumnMappingResponse])
async def list_columns(
    corpus_id: str, language: str, service: CodelistServiceDep
) -> list[ColumnMappingResponse]:
    views = await service.list_columns(CorpusId(corpus_id), language=language)
    return [_column_response(v) for v in views]


@router.put("/columns/mapping", response_model=ColumnMappingResponse)
async def map_column(body: MapColumnRequest, service: CodelistServiceDep) -> ColumnMappingResponse:
    try:
        view = await service.map_column(
            CorpusId(body.corpus_id), body.source_column, CodeAttributeId(body.code_attribute_id)
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _column_response(view)


@router.delete("/columns/mapping", status_code=status.HTTP_204_NO_CONTENT)
async def unmap_column(corpus_id: str, source_column: str, service: CodelistServiceDep) -> None:
    await service.unmap_column(CorpusId(corpus_id), source_column)
