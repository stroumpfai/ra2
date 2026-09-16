# NEW — reset and discard (sw-design.md §18). Not frozen.
"""Shared translation for the three discard routes.

`runs.py`, `evaluations.py` and `deliveries.py` each own one `DELETE`, and all
three answer with the same two shapes and the same two statuses. This module
holds that translation once: three copies of §18.2's status mapping would be
three places for one of them to drift into a 400 or a 422.

**Not a router.** It exports functions, not an `APIRouter` — the routes stay on
the resource routers they belong to, where a reader looking for "what can I do
to a run" finds them.
"""

from fastapi import HTTPException, status

from ra2.api.schemas import DiscardPreview, DiscardResponse
from ra2.services.readmodels import DiscardPreviewView

__all__ = ["conflict", "discard_preview", "discard_response"]


def discard_preview(view: DiscardPreviewView) -> DiscardPreview:
    """The read model, plus its two computed properties as data.

    `has_exportable` and `blocked` are rules the service owns (§18.2, §18.5);
    a client re-deriving them from the counts would be a second copy of the
    rule, and the first thing to fall out of step when a guard changes.
    """
    return DiscardPreview(
        kind=view.kind,
        target_id=view.target_id,
        label=view.label,
        runs=view.runs,
        extractions=view.extractions,
        scores=view.scores,
        mismatches=view.mismatches,
        tagged_mismatches=view.tagged_mismatches,
        files=view.files,
        active=view.active,
        active_detail=view.active_detail,
        cited_by=view.cited_by,
        has_exportable=view.has_exportable,
        blocked=view.blocked,
    )


def discard_response(view: DiscardPreviewView, *, forced: bool) -> DiscardResponse:
    """The receipt, built from the preview taken **before** the delete.

    That is the only moment those counts exist: nothing is written anywhere
    recording that a discard happened (§18.3), so this response is the whole
    of what the caller gets to keep.
    """
    return DiscardResponse(
        kind=view.kind,
        target_id=view.target_id,
        runs=view.runs,
        extractions=view.extractions,
        scores=view.scores,
        mismatches=view.mismatches,
        tagged_mismatches=view.tagged_mismatches,
        files=view.files,
        forced=forced,
    )


def conflict(exc: Exception) -> HTTPException:
    """Every guard in §18.2 is a 409.

    `RunActiveError` (G1) is final; `TaggedWorkPresentError` (G2) carries the
    count in its message and is overridable with `force`; `DeliveryCitedError`
    is final. One status, because from the caller's side they are one kind of
    answer — "not in this state" — and the message says which.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
