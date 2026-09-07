# STUB — bodies owned by C1 (feat/m4-api-deliveries). Not frozen.
"""`/api/v1/corpora` — list, create (freeze), get, delete.

Two responses that are contracts, not implementation details:
- a blocking freeze returns **422 with the findings** and creates nothing (J2);
- deleting a corpus an evaluation cites returns **409** (J3).
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import CorpusServiceDep
from ra2.api.schemas import (
    BlockingFindingsResponse,
    CorpusPage,
    CorpusResponse,
    CreateCorpusRequest,
    ErrorResponse,
)
from ra2.services.readmodels import SortDir

__all__ = ["router"]

router = APIRouter(prefix="/corpora", tags=["corpora"])

_NOT_BUILT = "not implemented until M4 (C1)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=CorpusPage)
async def list_corpora(
    service: CorpusServiceDep,
    sort_key: str = "imported_at",
    sort_dir: SortDir = SortDir.DESC,
    page: int = 1,
    page_size: int = 10,
) -> CorpusPage:
    raise _todo()


@router.post(
    "",
    response_model=CorpusResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": BlockingFindingsResponse}},
)
async def create_corpus(body: CreateCorpusRequest, service: CorpusServiceDep) -> CorpusResponse:
    """Freeze the selected files. All-or-nothing (sw-design.md §6.3)."""
    raise _todo()


@router.get("/{corpus_id}", response_model=CorpusResponse)
async def get_corpus(corpus_id: str, service: CorpusServiceDep) -> CorpusResponse:
    raise _todo()


@router.delete(
    "/{corpus_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_corpus(corpus_id: str, service: CorpusServiceDep) -> None:
    """409 when any evaluation cites the corpus (J3)."""
    raise _todo()
