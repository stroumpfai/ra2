# STUB — bodies owned by C1 (feat/m4-api-deliveries). Not frozen.
"""`/api/v1/corpora` — list, create (freeze), get, delete.

Two responses that are contracts, not implementation details:
- a blocking freeze returns **422 with the findings** and creates nothing (J2);
- deleting a corpus an evaluation cites returns **409** (J3).
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import CorpusServiceDep
from ra2.api.schemas import (
    BlockingFindingsResponse,
    CorpusPage,
    CorpusResponse,
    CreateCorpusRequest,
    ErrorResponse,
    FindingResponse,
    PageMeta,
)
from ra2.domain.findings import Finding
from ra2.domain.ids import CorpusId, DeliveryId
from ra2.services.errors import (
    BlockingFindingsError,
    CorpusLockedError,
    DeliveryNotAnalysedError,
    NotFoundError,
)
from ra2.services.readmodels import CorpusView, SortDir

__all__ = ["router"]

router = APIRouter(prefix="/corpora", tags=["corpora"])


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


def _corpus_response(view: CorpusView) -> CorpusResponse:
    return CorpusResponse(
        corpus_id=view.corpus_id,
        name=view.name,
        version=view.version,
        description=view.description,
        imported_at=view.imported_at,
        record_count=view.record_count,
        is_dev_sized=view.is_dev_sized,
        cp1252_canary_count=view.cp1252_canary_count,
        language_counts=dict(view.language_counts),
        delivery_id=view.delivery_id,
        locked_by_evaluations=view.locked_by_evaluations,
    )


def _blocking_findings_response(exc: BlockingFindingsError) -> JSONResponse:
    """422, body **is** `BlockingFindingsResponse` — nothing was created (J2).

    A plain `HTTPException` would nest this under a `"detail"` key; the
    contract is that the findings are top-level fields of the response body,
    so this builds the `JSONResponse` directly.
    """
    body = BlockingFindingsResponse(findings=[_finding_response(f) for f in exc.findings])
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: CorpusLockedError | DeliveryNotAnalysedError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("", response_model=CorpusPage)
async def list_corpora(
    service: CorpusServiceDep,
    sort_key: str = "imported_at",
    sort_dir: SortDir = SortDir.DESC,
    page: int = 1,
    page_size: int = 10,
) -> CorpusPage:
    result = await service.list_corpora(
        sort_key=sort_key, sort_dir=sort_dir, page=page, page_size=page_size
    )
    return CorpusPage(
        items=[_corpus_response(v) for v in result.items],
        meta=PageMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            sort_key=result.sort_key,
            sort_dir=result.sort_dir,
        ),
    )


@router.post(
    "",
    response_model=CorpusResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": BlockingFindingsResponse}},
)
async def create_corpus(
    body: CreateCorpusRequest, service: CorpusServiceDep
) -> CorpusResponse | JSONResponse:
    """Freeze the selected files. All-or-nothing (sw-design.md §6.3)."""
    try:
        corpus_id = await service.freeze(
            DeliveryId(body.delivery_id), name=body.name, description=body.description
        )
    except BlockingFindingsError as exc:
        return _blocking_findings_response(exc)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except DeliveryNotAnalysedError as exc:
        raise _conflict(exc) from exc
    view = await service.get(corpus_id)
    return _corpus_response(view)


@router.get("/{corpus_id}", response_model=CorpusResponse)
async def get_corpus(corpus_id: str, service: CorpusServiceDep) -> CorpusResponse:
    try:
        view = await service.get(CorpusId(corpus_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _corpus_response(view)


@router.delete(
    "/{corpus_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_corpus(corpus_id: str, service: CorpusServiceDep) -> None:
    """409 when any evaluation cites the corpus (J3)."""
    try:
        await service.delete(CorpusId(corpus_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except CorpusLockedError as exc:
        raise _conflict(exc) from exc
