# STUB — bodies owned by Y2 (feat/p5-api-mismatches). Not frozen.
"""`/api/v1/…/mismatches` — the review list, the tag, the tally and the CSV
(plan-phase-5.md §9, sw-design.md §17).

Thin translation only, the same idiom as `results.py` and `presence.py`. No
ORM object crosses this boundary and no decision is taken here.

Three rules this router carries, each of them a §17 fact rather than a
convention:

- **An evaluation with no mismatches is 200 with an empty list**, never a 404.
  "Nothing was wrong" is a result, and a status code forces a toast where the
  page should simply be in a state — the §16.7 reasoning, reapplied.
- **An unknown tag is 422, not a silent write.** The column is open so a
  fourth tag needs no migration; the wire is closed so nothing in this
  codebase creates one (`SD24`, §17.5). `TagMismatchRequest.tag` is a
  `MismatchTag`, so FastAPI answers before the service is reached.
- **Nothing here touches scoring.** There is no rescore route on this router
  and no import of one: §12's "the tag never feeds back into a metric" is an
  absent edge, and this is one of the places it is absent from (§17.3).

**M35 freezes the signatures. Y2 writes the bodies.**
"""

from fastapi import APIRouter, Query, Response

from ra2.api.deps import ExportServiceDep, MismatchServiceDep
from ra2.api.schemas import (
    MismatchListResponse,
    MismatchResponse,
    ReviewTallyResponse,
    TagMismatchRequest,
)
from ra2.domain.mismatch import TagFilter, TagState
from ra2.services.readmodels import SortDir

__all__ = ["router"]

router = APIRouter(tags=["mismatches"])

#: `export_service` writes UTF-8 with a BOM for Excel on Windows (N3); the
#: charset says so rather than leaving a browser to guess.
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


@router.get("/evaluations/{evaluation_id}/mismatches")
async def list_mismatches(
    evaluation_id: str,
    service: MismatchServiceDep,
    run: str | None = None,
    feature: str | None = None,
    tag_state: TagFilter = TagState.ANY,
    sort_key: str = "feature",
    sort_dir: SortDir = SortDir.ASC,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> MismatchListResponse:
    """The flat list, filtered, sorted and paged.

    `run` absent picks the evaluation's first run — there is no "all runs"
    scope (§17.6). An evaluation with no mismatches is **200 with an empty
    list**.
    """
    raise NotImplementedError


@router.get("/evaluations/{evaluation_id}/mismatches/tally")
async def mismatch_tally(
    evaluation_id: str,
    service: MismatchServiceDep,
    run: str | None = None,
    feature: str | None = None,
    tag_state: TagFilter = TagState.ANY,
) -> list[ReviewTallyResponse]:
    """Per-feature review counts, scoped to the **same filters** as the list,
    so the strip and the table cannot disagree (§17.4)."""
    raise NotImplementedError


@router.post("/mismatches/{mismatch_id}/tag")
async def tag_mismatch(
    mismatch_id: str, payload: TagMismatchRequest, service: MismatchServiceDep
) -> MismatchResponse:
    """Write one judgement. **Idempotent** — the same tag twice leaves one row
    and one `tagged_at`.

    404 for an unknown mismatch; 422 for a tag outside `MismatchTag`, which
    FastAPI answers before this function runs.
    """
    raise NotImplementedError


@router.delete("/mismatches/{mismatch_id}/tag")
async def clear_mismatch_tag(mismatch_id: str, service: MismatchServiceDep) -> MismatchResponse:
    """Clear the tag, `tagged_at` and `note` (Q4).

    Returns the row rather than a bare 204: the cleared row is what the screen
    redraws, and a body means it does not have to re-read to find out.
    """
    raise NotImplementedError


@router.get("/evaluations/{evaluation_id}/mismatches.csv")
async def mismatches_csv(
    evaluation_id: str,
    service: MismatchServiceDep,
    export: ExportServiceDep,
    run: str | None = None,
    feature: str | None = None,
    tag_state: TagFilter = TagState.ANY,
    sort_key: str = "feature",
    sort_dir: SortDir = SortDir.ASC,
) -> Response:
    """The currently filtered, currently sorted rows as CSV.

    The exporter is handed **the rows this endpoint just read**, not a filter
    to re-run (`P4-D3`, §7). It carries the tag and the note, because an
    export whose point is review has to carry the review.
    """
    raise NotImplementedError
