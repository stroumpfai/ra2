# STUB — bodies owned by S4 (feat/p4-persistence). Not frozen.
"""`score` persistence (mvp-spec.md §5/§11, sw-design.md §16.1).

**One `(run, feature)`, one commit** — the boundary that makes the scoring pass
resumable. `write_feature` replaces one pair's rows wholesale: they are a pure
function of immutable inputs, so a re-score either reproduces them
byte-for-byte or the scorer changed, and replacement is correct either way.
That is the opposite of `mismatch`, which is upserted (see `mismatch_repo`).

**There is deliberately no scoring-status column.** `scored_feature_ids` is the
progress indicator *and* the resume key — "the features of this run with no
rows are the work left" — so the two cannot disagree, exactly as
`ExtractionRepository.pending_record_ids` and `count_done` cannot (§15.3, F5).
Do not add a `scored_at`.

`language` is `NOT NULL` with `domain.scoring.ALL_LANGUAGES` (`'*'`) for the
all-languages row (`SD16`): it is part of the composite key, and SQL treats two
NULLs as distinct in a unique constraint.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import FeatureId, RunId
from ra2.domain.scoring import ScoreRow
from ra2.persistence.models import Score

__all__ = ["ScoreRepository"]


class ScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write_feature(
        self, run_id: RunId, feature_id: FeatureId, rows: Sequence[ScoreRow]
    ) -> None:
        """Replace this `(run, feature)`'s rows. Does **not** commit — the
        caller owns the transaction boundary (§16.1)."""
        raise NotImplementedError

    async def scored_feature_ids(self, run_id: RunId) -> frozenset[FeatureId]:
        """Which features this run already has rows for — progress and resume,
        one query, one answer."""
        raise NotImplementedError

    async def for_run(self, run_id: RunId) -> Sequence[Score]:
        """Every stored row, unsuppressed. Suppression is a **read-time** rule
        applied in `results_service` from the evaluation's floor (`SD19`), never
        here — which is what lets the floor change without a re-score."""
        raise NotImplementedError
