# STUB — bodies owned by S4 (feat/p4-persistence). Not frozen.
"""`mismatch` persistence (mvp-spec.md §5/§12, sw-design.md §16.6).

**The one mutable row in this pipeline**, and the one repository in the project
whose write must preserve something. Everything else is append-only: Do-NOT #2
covers `corpus`, `record` and `extraction`, prompt templates are copy-on-write,
code tables are superseded rather than edited.

`upsert_feature` rewrites the derived columns — `record_value`,
`extracted_value`, `evidence_span` — and **leaves `analyst_tag`, `tagged_at`
and `note` alone**, keyed on `UNIQUE (run_id, record_id, feature_id)`. A row
that no longer mismatches is deleted; a row that still does keeps its tag.

`DELETE`-then-`INSERT` is the obvious implementation and it is wrong: it
destroys review work silently, at the moment a developer is most confident,
because they have just fixed the scorer (SD21, R5). The preservation test is
what makes this a fact rather than a comment.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import FeatureId, RunId
from ra2.persistence.models import Mismatch

__all__ = ["MismatchRepository", "MismatchWrite"]


class MismatchWrite:
    """One `wrong` outcome to persist. Carries no review columns — a writer
    that cannot name `analyst_tag` cannot overwrite it."""

    __slots__ = ("evidence_span", "extracted_value", "record_id", "record_value")


class MismatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_feature(
        self, run_id: RunId, feature_id: FeatureId, rows: Sequence[MismatchWrite]
    ) -> None:
        """Replace this `(run, feature)`'s mismatches, **preserving tags**.

        Does not commit: the caller owns the boundary, and a feature's `score`
        rows and its `mismatch` rows go in together (§16.1).
        """
        raise NotImplementedError

    async def for_run(self, run_id: RunId) -> Sequence[Mismatch]:
        """Phase 4 writes these and never reads them in anger — the review view
        is F11 (plan-phase-4.md §1 Q1). This exists for the tests that assert
        tags survived a re-score."""
        raise NotImplementedError
