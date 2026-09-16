# STUB — bodies owned by U1 (feat/p4-api-results). Not frozen.
"""`/api/v1/evaluations/{id}/results` — tab 1, plus scoring status and re-score
(plan-phase-4.md §9, sw-design.md §16.7).

**An unscored run is 200 with `scored: false`, never a 404.** The UI renders a
state, and an error status would force exactly the toast §16.7 rejects — the
same reasoning §15.5 applied to an unreachable endpoint, and the same shape
`GET /api/v1/models` already has.

**A suppressed cell never serialises as a number.** It goes out as its typed
insufficient-data shape carrying its `n` and the floor, and U1's tests assert
the absence at the JSON layer as well as the DOM: four layers, four chances to
leak a number nobody measured.

Thin translation only, same idiom as `runs.py`/`evaluations.py`.
"""

from fastapi import APIRouter

__all__ = ["router"]

router = APIRouter(tags=["results"])
