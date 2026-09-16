# STUB — bodies owned by U2 (feat/p4-api-presence-ranking). Not frozen.
"""`/api/v1/evaluations/{id}/presence` — tab 2 (plan-phase-4.md §9).

**Presence figures never serialise without their Goal 1 companions**
(mvp-spec.md §11.2, "a weak extractor manufactures false 'missing' flags").
`readmodels.PresenceRow` makes that a type error internally; here it is
asserted at the **schema** level, so a wire format cannot quietly drop the
column the read model is careful to carry.

The per-record CSV is `export_service`'s existing conventions unchanged —
UTF-8 with a BOM, `;`-delimited, a comment line naming corpus and version, and
the currently filtered and sorted rows only (sw-design.md §7).

Thin translation only.
"""

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from ra2.api.deps import ExportServiceDep, ResultsServiceDep
from ra2.api.schemas import (
    CrossTabResponse,
    FlagInconsistencyResponse,
    Goal1CompanionResponse,
    ModelColumnResponse,
    PerRecordPage,
    PerRecordResponse,
    PresenceRowResponse,
    PresenceTabResponse,
)
from ra2.api.v1.results import cell_response, descriptor_response
from ra2.domain.ids import EvaluationId
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import Page, PerRecordRow, PresenceTabView

__all__ = ["router"]

router = APIRouter(tags=["presence"])

#: `export_service` writes UTF-8 with a BOM for Excel on Windows (N3); the
#: charset says so rather than leaving a browser to guess.
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


def _records_page(page: Page[PerRecordRow]) -> PerRecordPage:
    return PerRecordPage(
        items=[
            PerRecordResponse(
                record_id=row.record_id,
                anonymised=row.anonymised,
                record_value=row.record_value,
                finding=row.finding,
                language=row.language,
                language_confidence=row.language_confidence,
            )
            for row in page.items
        ],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


def _presence_tab(view: PresenceTabView, *, scored: bool) -> PresenceTabResponse:
    return PresenceTabResponse(
        scored=scored,
        descriptor=descriptor_response(view.descriptor),
        models=[
            ModelColumnResponse(model_id=m.model_id, tag=m.tag, digest=m.digest)
            for m in view.models
        ],
        model_id=view.model_id,
        rows=[
            PresenceRowResponse(
                feature_key=row.feature_key,
                rates={lang: cell_response(cell) for lang, cell in row.rates.items()},
                # **Required, not optional** (§11.2). A wire format that could
                # omit this is a wire format that will, and "a weak extractor
                # manufactures false 'missing' flags" is the reason it must
                # not.
                goal1=Goal1CompanionResponse(
                    f1=row.goal1.f1,
                    precision=row.goal1.precision,
                    recall=row.goal1.recall,
                ),
            )
            for row in view.rows
        ],
        cross_tab=(
            CrossTabResponse(
                feature_key=view.cross_tab.feature_key,
                model_id=view.cross_tab.model_id,
                hit_present=view.cross_tab.hit_present,
                hit_absent=view.cross_tab.hit_absent,
                wrong_present=view.cross_tab.wrong_present,
                wrong_absent=view.cross_tab.wrong_absent,
                missing_present=view.cross_tab.missing_present,
                missing_absent=view.cross_tab.missing_absent,
            )
            if view.cross_tab
            else None
        ),
        flag_inconsistency=[
            FlagInconsistencyResponse(model_id=row.model_id, cell=cell_response(row.cell))
            for row in view.flag_inconsistency
        ],
        records=_records_page(view.records) if view.records else None,
    )


@router.get("/evaluations/{evaluation_id}/presence")
async def presence_tab(
    evaluation_id: str,
    service: ResultsServiceDep,
    model_id: str | None = None,
    feature_key: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PresenceTabResponse:
    """Tab 2, one model at a time. Unscored is 200 with `scored: false`."""
    try:
        view = await service.presence_tab(
            EvaluationId(evaluation_id),
            model_id=model_id,
            feature_key=feature_key,
            page=page,
            page_size=page_size,
        )
        statuses = await service.scoring_status(EvaluationId(evaluation_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _presence_tab(view, scored=any(s.is_scored for s in statuses))


@router.get("/evaluations/{evaluation_id}/presence/records")
async def presence_records(
    evaluation_id: str,
    service: ResultsServiceDep,
    model_id: str | None = None,
    feature_key: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PerRecordPage:
    """The actionable form of Goal 2 — records recorded but not written."""
    try:
        rows = await service.presence_records(
            EvaluationId(evaluation_id),
            model_id=model_id,
            feature_key=feature_key,
            page=page,
            page_size=page_size,
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return _records_page(rows)


@router.get("/evaluations/{evaluation_id}/presence/records.csv")
async def presence_records_csv(
    evaluation_id: str,
    results: ResultsServiceDep,
    export: ExportServiceDep,
    model_id: str | None = None,
    feature_key: str | None = None,
) -> Response:
    """The per-record list as CSV.

    The exporter is handed **the rows this endpoint just read**, not a filter
    to re-run (`P4-D3`): §7's rule is that an export writes the currently
    filtered, currently sorted table, and re-fetching inside the exporter is
    how a CSV comes to disagree with the screen it was exported from.
    """
    try:
        rows = await results.presence_records(
            EvaluationId(evaluation_id),
            model_id=model_id,
            feature_key=feature_key,
            page=1,
            page_size=100_000,
        )
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    payload = export.presence_records_csv(
        rows.items,
        evaluation_id=EvaluationId(evaluation_id),
        model_id=model_id or "",
        feature_key=feature_key or "",
    )
    return Response(
        content=payload,
        media_type=CSV_MEDIA_TYPE,
        headers={"content-disposition": (f'attachment; filename="presence-{evaluation_id}.csv"')},
    )
