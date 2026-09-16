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

from fastapi import APIRouter

__all__ = ["router"]

router = APIRouter(tags=["presence"])
