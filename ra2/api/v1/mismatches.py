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

**M35 froze the signatures; Y2 wrote the bodies.**
"""

from fastapi import APIRouter, HTTPException, Query, Response, status

from ra2.api.deps import ExportServiceDep, MismatchServiceDep
from ra2.api.schemas import (
    MismatchFeatureResponse,
    MismatchFiltersResponse,
    MismatchListResponse,
    MismatchPage,
    MismatchResponse,
    ModelColumnResponse,
    ReviewTallyResponse,
    TagMismatchRequest,
)
from ra2.api.v1.results import descriptor_response
from ra2.domain.ids import EvaluationId, FeatureId, MismatchId, RunId
from ra2.domain.mismatch import TagFilter, TagState
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import (
    MismatchListView,
    MismatchRowView,
    ReviewTallyView,
    SortDir,
)

__all__ = ["router"]

router = APIRouter(tags=["mismatches"])

#: `export_service` writes UTF-8 with a BOM for Excel on Windows (N3); the
#: charset says so rather than leaving a browser to guess.
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _row(view: MismatchRowView) -> MismatchResponse:
    """One row.

    `analyst_tag` goes out as the **stored string** and `tag` as the narrowing
    beside it, both from the read model's own properties — the wire mirrors
    `SD24`'s asymmetry rather than resolving it, so a client renders an
    unrecognised value as itself instead of as nothing.
    """
    return MismatchResponse(
        mismatch_id=str(view.mismatch_id),
        record_id=str(view.record_id),
        anonymised=view.anonymised,
        feature_id=str(view.feature_id),
        feature_key=view.feature_key,
        record_value=view.record_value,
        extracted_value=view.extracted_value,
        evidence_span=view.evidence_span,
        analyst_tag=view.analyst_tag,
        tagged_at=view.tagged_at,
        note=view.note,
        tag=view.tag,
        is_other=view.is_other,
        reviewed=view.reviewed,
    )


def _tally(view: ReviewTallyView) -> ReviewTallyResponse:
    """One feature's counts.

    `counts` is keyed by `MismatchTag` **value** and always carries all three,
    because `ReviewTally` does — a client must not have to guess whether a
    missing key means "none" or "not counted".
    """
    return ReviewTallyResponse(
        feature_id=str(view.feature_id),
        feature_key=view.feature_key,
        total=view.tally.total,
        reviewed=view.tally.reviewed,
        untagged=view.tally.untagged,
        counts={tag.value: count for tag, count in view.tally.counts.items()},
        other=view.tally.other,
    )


def _list(view: MismatchListView) -> MismatchListResponse:
    return MismatchListResponse(
        descriptor=descriptor_response(view.descriptor),
        runs=[
            ModelColumnResponse(model_id=run.model_id, tag=run.tag, digest=run.digest)
            for run in view.runs
        ],
        run_label=view.run_label,
        run_finished_at=view.run_finished_at,
        features=[
            MismatchFeatureResponse(
                feature_id=str(option.feature_id),
                feature_key=option.feature_key,
                total=option.total,
            )
            for option in view.features
        ],
        filters=MismatchFiltersResponse(
            run_id=str(view.filters.run_id),
            feature_id=None if view.filters.feature_id is None else str(view.filters.feature_id),
            tag_state=view.filters.tag_state,
        ),
        rows=MismatchPage(
            items=[_row(row) for row in view.rows.items],
            total=view.rows.total,
            page=view.rows.page,
            page_size=view.rows.page_size,
            sort_key=view.rows.sort_key,
            sort_dir=view.rows.sort_dir,
        ),
        tallies=[_tally(entry) for entry in view.tallies],
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


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
    scope (§17.6). An evaluation whose run has no mismatches is **200 with an
    empty list**: "nothing was wrong" is a result, and a status code would
    force a toast where the page should simply be in a state.
    """
    try:
        view = await service.list_mismatches(
            EvaluationId(evaluation_id),
            run_id=RunId(run) if run else None,
            feature_id=FeatureId(feature) if feature else None,
            tag_state=tag_state,
            sort_key=sort_key,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _list(view)


@router.get("/evaluations/{evaluation_id}/mismatches/tally")
async def mismatch_tally(
    evaluation_id: str,
    service: MismatchServiceDep,
    run: str | None = None,
    feature: str | None = None,
    tag_state: TagFilter = TagState.ANY,
) -> list[ReviewTallyResponse]:
    """Per-feature review counts, scoped to the **same filters** as the list,
    so the strip and the table cannot disagree (§17.4).

    It reads through the same service call the list does rather than through
    `MismatchTally`: that protocol takes a session, and a router does not own
    one. What it gets back is the same tuple the list carries, which is the
    point — one read, one answer.
    """
    try:
        view = await service.list_mismatches(
            EvaluationId(evaluation_id),
            run_id=RunId(run) if run else None,
            feature_id=FeatureId(feature) if feature else None,
            tag_state=tag_state,
            page=1,
            page_size=1,
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return [_tally(entry) for entry in view.tallies]


@router.post("/mismatches/{mismatch_id}/tag")
async def tag_mismatch(
    mismatch_id: str, payload: TagMismatchRequest, service: MismatchServiceDep
) -> MismatchResponse:
    """Write one judgement. **Idempotent** — the same tag twice leaves one row
    and one `tagged_at`.

    404 for an unknown mismatch. **422 for a tag outside `MismatchTag`**,
    answered by FastAPI's own validation before this function runs: the column
    is open so a fourth tag needs no migration, and the wire is closed so
    nothing in this codebase creates one (`SD24`, §17.5).
    """
    try:
        view = await service.tag(MismatchId(mismatch_id), tag=payload.tag, note=payload.note)
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _row(view)


@router.delete("/mismatches/{mismatch_id}/tag")
async def clear_mismatch_tag(mismatch_id: str, service: MismatchServiceDep) -> MismatchResponse:
    """Clear the tag, `tagged_at` and `note` (Q4).

    Returns the row rather than a bare 204: the cleared row is what the screen
    redraws, and a body means it does not have to re-read to find out.
    """
    try:
        view = await service.clear_tag(MismatchId(mismatch_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _row(view)


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
    try:
        view = await service.export_rows(
            EvaluationId(evaluation_id),
            run_id=RunId(run) if run else None,
            feature_id=FeatureId(feature) if feature else None,
            tag_state=tag_state,
            sort_key=sort_key,
            sort_dir=sort_dir,
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    payload = export.mismatches_csv(
        view.rows.items,
        evaluation_id=EvaluationId(evaluation_id),
        run_label=view.run_label,
        filter_label=_filter_label(view),
    )
    return Response(
        content=payload,
        media_type=CSV_MEDIA_TYPE,
        headers={"content-disposition": f'attachment; filename="mismatches-{evaluation_id}.csv"'},
    )


def _filter_label(view: MismatchListView) -> str:
    """What the comment line says this file is a list of.

    Composed here rather than in `export_service` because it is **copy**, and
    the exporter's job is to write the rows it was handed — the same division
    `PRESENCE_FINDING` makes one service over.
    """
    parts = [f"tag {view.filters.tag_state}"]
    if view.filters.feature_id is not None:
        feature = next(
            (o.feature_key for o in view.features if o.feature_id == view.filters.feature_id),
            str(view.filters.feature_id),
        )
        parts.append(f"feature {feature}")
    return " · ".join(parts)
