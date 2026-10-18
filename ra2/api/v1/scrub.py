# NEW — feat/text-scrubbing. Not frozen.
"""`/api/v1/scrub` — the scrub rules and lists, and the dry run (sw-design.md §19).

Thin translation only, in `codelists.py`'s idiom: `_xxx_response(view)`
mappers, and a `JSONResponse` built directly for the 422 so the refusal's
fields are top-level, not nested under `"detail"`.

- `GET    /scrub/active`                    what the next freeze applies
- `GET    /scrub/versions`                  every version, newest first
- `POST   /scrub/lists/{kind}`              import one file (multipart)
- `DELETE /scrub/lists/{kind}`              a version without that kind
- `GET    /scrub/lists/{kind}/entries`      search the active list, paged
- `POST   /scrub/try`                       the active rules over one sentence
- `GET    /scrub/preview?delivery_id=`      the dry run: what a freeze would count

**Nothing here logs a body.** `POST /scrub/try` carries a sentence that may
be real narrative typed in to test; it is scrubbed and answered, never
stored, and the request log records the path only (`data-handling.md` §5.1).
"""

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import CorpusServiceDep, ScrubServiceDep
from ra2.api.schemas import (
    PageMeta,
    ScrubCountResponse,
    ScrubEntryPage,
    ScrubEntryResponse,
    ScrubHitResponse,
    ScrubImportErrorItem,
    ScrubImportErrorResponse,
    ScrubImportResponse,
    ScrubListResponse,
    ScrubMostHitResponse,
    ScrubNoticeResponse,
    ScrubPreviewResponse,
    ScrubRuleResponse,
    ScrubRulesetResponse,
    ScrubTryRequest,
    ScrubTryResponse,
    ScrubVersionResponse,
)
from ra2.domain.ids import DeliveryId, ScrubRulesetId
from ra2.domain.scrub import ListKind
from ra2.services.errors import DeliveryNotAnalysedError, NotFoundError, ScrubImportRefusedError
from ra2.services.readmodels import (
    ScrubImportView,
    ScrubNoticeView,
    ScrubPreviewView,
    ScrubRulesetView,
    ScrubVersionView,
)

__all__ = ["router"]

router = APIRouter(prefix="/scrub", tags=["scrub"])


# ---------------------------------------------------------------------------
# read model -> wire schema
# ---------------------------------------------------------------------------


def _notices(notices: tuple[ScrubNoticeView, ...]) -> list[ScrubNoticeResponse]:
    return [
        ScrubNoticeResponse(code=n.code, count=n.count, examples=list(n.examples)) for n in notices
    ]


def _ruleset_response(view: ScrubRulesetView) -> ScrubRulesetResponse:
    return ScrubRulesetResponse(
        ruleset_id=view.ruleset_id,
        version=view.version,
        created_at=view.created_at,
        fingerprint=view.fingerprint,
        mandatory_version=view.mandatory_version,
        rules=[
            ScrubRuleResponse(
                rule_id=r.rule_id,
                tag=r.tag,
                pattern=r.pattern,
                source=r.source,
                description=r.description,
                must_match=list(r.must_match),
                must_not_match=list(r.must_not_match),
            )
            for r in view.rules
        ],
        lists=[
            ScrubListResponse(
                scrub_list_id=lst.scrub_list_id,
                kind=lst.kind,
                filename=lst.filename,
                sha256=lst.sha256,
                imported_at=lst.imported_at,
                entry_count=lst.entry_count,
                notices=_notices(lst.notices),
            )
            for lst in view.lists
        ],
        protected=list(view.protected),
    )


def _import_response(view: ScrubImportView) -> ScrubImportResponse:
    return ScrubImportResponse(
        ruleset=_ruleset_response(view.ruleset),
        no_change=view.no_change,
        notices=_notices(view.notices),
    )


def _version_response(view: ScrubVersionView) -> ScrubVersionResponse:
    return ScrubVersionResponse(
        ruleset_id=view.ruleset_id,
        version=view.version,
        created_at=view.created_at,
        fingerprint=view.fingerprint,
        components=dict(view.components),
        corpus_count=view.corpus_count,
    )


def _preview_response(view: ScrubPreviewView) -> ScrubPreviewResponse:
    return ScrubPreviewResponse(
        ruleset_id=view.ruleset_id,
        version=view.version,
        fingerprint=view.fingerprint,
        counts=[
            ScrubCountResponse(
                rule_id=c.rule_id, tag=c.tag, source=c.source, hits=c.hits, records=c.records
            )
            for c in view.counts
        ],
        most_hit=[ScrubMostHitResponse(entry=entry, hits=hits) for entry, hits in view.most_hit],
        records=view.records,
        records_changed=view.records_changed,
        timed_out_rule=view.timed_out_rule,
    )


def _refused(exc: ScrubImportRefusedError) -> JSONResponse:
    """422, body **is** `ScrubImportErrorResponse`: nothing was written."""
    body = ScrubImportErrorResponse(
        import_errors=[
            ScrubImportErrorItem(code=e.code.value, rule_id=e.rule_id, detail=dict(e.detail))
            for e in exc.import_errors
        ]
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("/active", response_model=ScrubRulesetResponse)
async def active(service: ScrubServiceDep) -> ScrubRulesetResponse:
    return _ruleset_response(await service.active())


@router.get("/versions", response_model=list[ScrubVersionResponse])
async def versions(service: ScrubServiceDep) -> list[ScrubVersionResponse]:
    return [_version_response(v) for v in await service.versions()]


@router.post(
    "/lists/{kind}",
    response_model=ScrubImportResponse,
    responses={422: {"model": ScrubImportErrorResponse}},
)
async def import_list(
    kind: ListKind, file: UploadFile, service: ScrubServiceDep
) -> ScrubImportResponse | JSONResponse:
    """§19.7: checked whole, with the mandatory rules and the active set's
    other files; refused whole, or a new version."""
    content = await file.read()
    try:
        view = await service.import_list(kind, file.filename or "", content)
    except ScrubImportRefusedError as exc:
        return _refused(exc)
    return _import_response(view)


@router.delete(
    "/lists/{kind}",
    response_model=ScrubImportResponse,
    responses={422: {"model": ScrubImportErrorResponse}},
)
async def remove_list(
    kind: ListKind, service: ScrubServiceDep
) -> ScrubImportResponse | JSONResponse:
    try:
        view = await service.remove_list(kind)
    except ScrubImportRefusedError as exc:
        return _refused(exc)
    return _import_response(view)


@router.get("/lists/{kind}/entries", response_model=ScrubEntryPage)
async def entries(
    kind: ListKind,
    service: ScrubServiceDep,
    query: str = "",
    page: int = 1,
    page_size: int = 50,
) -> ScrubEntryPage:
    result = await service.entries(kind, query=query, page=page, page_size=page_size)
    return ScrubEntryPage(
        items=[ScrubEntryResponse(entry=e.entry, key=e.key) for e in result.items],
        meta=PageMeta(
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            sort_key=result.sort_key,
            sort_dir=result.sort_dir,
        ),
    )


@router.post("/try", response_model=ScrubTryResponse)
async def try_text(body: ScrubTryRequest, service: ScrubServiceDep) -> ScrubTryResponse:
    view = await service.try_text(body.text)
    return ScrubTryResponse(
        text=view.text,
        hits=[
            ScrubHitResponse(
                rule_id=h.rule_id, tag=h.tag, placeholder=h.placeholder, start=h.start, end=h.end
            )
            for h in view.hits
        ],
        timed_out_rule=view.timed_out_rule,
    )


@router.get("/preview", response_model=ScrubPreviewResponse)
async def preview(
    delivery_id: str, service: CorpusServiceDep, scrub_ruleset_id: str | None = None
) -> ScrubPreviewResponse:
    """The dry run (§19.7): what `POST /corpora` would count for this
    delivery's selected files. Nothing is written."""
    try:
        view = await service.scrub_preview(
            DeliveryId(delivery_id),
            scrub_ruleset_id=ScrubRulesetId(scrub_ruleset_id) if scrub_ruleset_id else None,
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except DeliveryNotAnalysedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _preview_response(view)
