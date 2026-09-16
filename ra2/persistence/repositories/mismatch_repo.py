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

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import FeatureId, MismatchId, RecordId, RunId
from ra2.persistence.models import Mismatch

__all__ = ["MismatchRepository", "MismatchWrite"]


@dataclass(frozen=True, slots=True)
class MismatchWrite:
    """One `wrong` outcome to persist.

    **Carries no review columns.** A writer that cannot name `analyst_tag`
    cannot overwrite it — the preservation rule is a property of this type
    before it is a property of the query (SD21).
    """

    record_id: RecordId
    record_value: str | None
    extracted_value: str | None
    evidence_span: str | None


class MismatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_feature(
        self,
        run_id: RunId,
        feature_id: FeatureId,
        rows: Sequence[MismatchWrite],
        *,
        new_id: Callable[[], str],
    ) -> None:
        """Replace this `(run, feature)`'s mismatches, **preserving tags**.

        Does not commit: the caller owns the boundary, and a feature's `score`
        rows and its `mismatch` rows go in together (§16.1).

        `new_id` is a plain callable rather than an injected `IdFactory`:
        `ra2/persistence/` may import `domain`, SQLAlchemy and Alembic, and
        **not `ra2/infra/`** (sw-design.md §1.1). Ids are minted in
        `services/`, the way `RelationalCensusMaterialiser` takes its `ids`,
        and the repository is handed the one function it needs.
        """
        existing = {
            row.record_id: row
            for row in (
                await self._session.execute(
                    select(Mismatch).where(
                        Mismatch.run_id == run_id, Mismatch.feature_id == feature_id
                    )
                )
            ).scalars()
        }
        incoming = {row.record_id: row for row in rows}

        # A record that no longer mismatches loses its row — and with it any
        # tag. That is correct: the tag described a mismatch that no longer
        # exists, and keeping it would leave review work attached to nothing.
        for record_id, row in existing.items():
            if record_id not in incoming:
                await self._session.delete(row)

        for record_id, write in incoming.items():
            stored = existing.get(record_id)
            if stored is None:
                self._session.add(
                    Mismatch(
                        id=MismatchId(new_id()),
                        run_id=run_id,
                        record_id=record_id,
                        feature_id=feature_id,
                        record_value=write.record_value,
                        extracted_value=write.extracted_value,
                        evidence_span=write.evidence_span,
                    )
                )
                continue
            # **The three review columns are untouched.** This is the whole
            # point of the method: `DELETE`-then-`INSERT` would be shorter and
            # would destroy an analyst's work silently, at the moment a
            # developer is most confident — they have just fixed the scorer.
            stored.record_value = write.record_value
            stored.extracted_value = write.extracted_value
            stored.evidence_span = write.evidence_span
        await self._session.flush()

    async def for_run(self, run_id: RunId) -> Sequence[Mismatch]:
        """Phase 4 writes these and never reads them in anger — the review view
        is F11 (plan-phase-4.md §1 Q1). This exists for the tests that assert
        tags survived a re-score."""
        result = await self._session.execute(
            select(Mismatch)
            .where(Mismatch.run_id == run_id)
            .order_by(Mismatch.feature_id, Mismatch.record_id)
        )
        return list(result.scalars())
