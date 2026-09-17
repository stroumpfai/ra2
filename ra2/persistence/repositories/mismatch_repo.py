# STUB — bodies owned by S4 (phase 4) and W1 (phase 5). Not frozen.
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

**Phase 5 adds the other half of that contract** (sw-design.md §17.1): the
three review columns acquire a writer. The split is now symmetric and neither
side writes the other's — `upsert_feature` rewrites the derived three and
**is unchanged**, `set_tag` writes the review three and nothing else, and
`MismatchWrite` still cannot name a review column.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import FeatureId, MismatchId, RecordId, RunId
from ra2.domain.mismatch import TagFilter
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

    # --- phase 5 (M35 signatures, W1 bodies). sw-design.md §17 -------------
    #
    # The review side of the ownership split (§17.1). `upsert_feature` above
    # is the scorer's side and must stay exactly as it is: the tag-preservation
    # test that guards it belongs to phase 4.

    async def list_for(
        self,
        run_id: RunId,
        *,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter,
        sort_key: str,
        descending: bool,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Mismatch], int]:
        """One filtered, sorted, paged page of a run's mismatches, and the
        unpaged total.

        **One run at a time** (§17.6) — there is no evaluation-wide overload,
        because a list mixing two models' mismatches for the same record and
        feature is the cross-model agreement §16.9 defers.

        `sort_key` is one of `domain.mismatch.MISMATCH_SORT_KEYS` and there is
        no fifth; **sorting is stable on ties**, so paging a list whose rows
        share a feature does not reshuffle it between page 1 and page 2.

        The statement count is **bounded and asserted** on a 1 000-row run
        (the R4 lesson, one table over): a per-row lookup of the feature key or
        the record's anonymisation flag is exactly the N+1 this signature
        exists to make unwritable.
        """
        raise NotImplementedError

    async def set_tag(
        self,
        mismatch_id: MismatchId,
        *,
        tag: str | None,
        note: str | None,
        now: datetime,
    ) -> Mismatch | None:
        """Write the **three review columns and nothing else** (§17.1).

        `tag=None` clears, and **clears `tagged_at` with it** — a cleared row
        that kept its timestamp would read as reviewed in the `Reviewed`
        column and be counted as untagged in the tally.

        `record_value`, `extracted_value` and `evidence_span` come out
        byte-identical. That is asserted on the row rather than on a count,
        and it is the mirror of the assertion that guards `upsert_feature`.

        Does not commit: the caller owns the transaction boundary, as
        everywhere else in this package. Returns `None` for an unknown id, so
        the service raises `NotFoundError` rather than the repository owning
        an HTTP fact.

        Takes `now` rather than reading a clock: `ra2/persistence/` may not
        import `ra2/infra/` (sw-design.md §1.1), the same reason
        `upsert_feature` is handed `new_id`.
        """
        raise NotImplementedError

    async def tally_for(
        self,
        run_id: RunId,
        *,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter,
    ) -> Mapping[FeatureId, Mapping[str | None, int]]:
        """Stored tag values and their row counts, per feature, for one run.

        **One grouped query per run, never one per feature** (§17.4):

            SELECT feature_id, analyst_tag, COUNT(*) FROM mismatch
             WHERE run_id = ? GROUP BY feature_id, analyst_tag

        `ix_mismatch_run_id_feature_id` already covers it. The return shape is
        what `domain.mismatch.tally` takes, so the grouping survives all the
        way into the domain instead of being expanded into rows and recounted.

        Takes the same filters as `list_for` so the strip under the table and
        the table itself cannot disagree — the one exception being
        `feature_id`, which scopes both identically.
        """
        raise NotImplementedError
