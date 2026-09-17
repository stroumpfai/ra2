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
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import FeatureId, MismatchId, RecordId, RunId
from ra2.domain.mismatch import MismatchTag, TagFilter, TagState
from ra2.persistence.models import Feature, Mismatch, Record

__all__ = ["MismatchListRow", "MismatchRepository", "MismatchWrite"]


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


@dataclass(frozen=True, slots=True)
class MismatchListRow:
    """One row of the review list, **with the two joined facts it needs**.

    `list_for` returns these rather than `Mismatch` objects, and that is what
    makes the N+1 unwritable rather than merely discouraged (`R4`, one table
    over). The Feature column shows `feature.key` and `mvp-spec.md` §13
    requires the anonymisation marking wherever record text is shown — so a
    caller handed bare ORM rows would have to walk a relationship per row to
    draw a page, which is exactly the shape sw-design.md §17.8 rules out.

    Both come out of the same `SELECT` as the mismatch itself.
    """

    id: MismatchId
    record_id: RecordId
    feature_id: FeatureId
    #: `feature.key` — the Feature column, the filter option and the tally
    #: strip all name the same string (amendment:
    #: feat/p5-mismatch-domain-persistence).
    feature_key: str
    #: `record.text_anonymised_flag` (mvp-spec.md §13).
    anonymised: bool
    record_value: str | None
    extracted_value: str | None
    evidence_span: str | None
    #: The stored value, **verbatim** — never narrowed here. A value
    #: `MismatchTag` does not name has to survive the whole way to the screen
    #: (`SD24`, §17.5).
    analyst_tag: str | None
    tagged_at: datetime | None
    note: str | None


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

    # --- phase 5 (W1). sw-design.md §17 -----------------------------------
    #
    # The review side of the ownership split (§17.1). `upsert_feature` above
    # is the scorer's side and is unchanged: the tag-preservation test that
    # guards it belongs to phase 4.

    async def list_for(
        self,
        run_id: RunId,
        *,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
        sort_key: str = "feature",
        descending: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[Sequence[MismatchListRow], int]:
        """One filtered, sorted, paged page of a run's mismatches, and the
        unpaged total.

        **One run at a time** (§17.6) — there is no evaluation-wide overload,
        because a list mixing two models' mismatches for the same record and
        feature is the cross-model agreement §16.9 defers.

        `sort_key` is one of `domain.mismatch.MISMATCH_SORT_KEYS` and there is
        no fifth. **Sorting is stable on ties**: every order ends in the
        mismatch id, so paging a list whose rows share a feature — which is
        most of them — does not reshuffle between page 1 and page 2 and cannot
        show a row twice or skip one.

        **Two statements, whatever the run holds**: one page, one count. The
        feature key and the anonymisation flag are joined rather than looked up
        (`MismatchListRow`), which is what keeps that true.
        """
        where = self._filters(run_id, feature_id=feature_id, tag_state=tag_state)
        page = (
            select(Mismatch, Feature.key, Record.text_anonymised_flag)
            .join(Feature, Feature.id == Mismatch.feature_id)
            .join(Record, Record.id == Mismatch.record_id)
            .where(*where)
            .order_by(*self._order(sort_key, descending=descending))
            .offset(offset)
            .limit(limit)
        )
        rows = [_to_row(*found) for found in (await self._session.execute(page)).all()]
        total = await self._session.scalar(select(func.count()).select_from(Mismatch).where(*where))
        return rows, total or 0

    async def set_tag(
        self,
        mismatch_id: MismatchId,
        *,
        tag: str | None,
        note: str | None,
        now: datetime,
    ) -> MismatchListRow | None:
        """Write the **three review columns and nothing else** (§17.1).

        `tag=None` clears, and **clears `tagged_at` and `note` with it** — a
        cleared row that kept its timestamp would read as reviewed in the
        `Reviewed` column while counting as untagged in the tally, and a note
        annotates a judgement that no longer exists.

        `record_value`, `extracted_value` and `evidence_span` come out
        byte-identical. That is asserted on the row rather than on a count, and
        it is the mirror of the assertion that guards `upsert_feature`.

        Does not commit: the caller owns the transaction boundary, as
        everywhere else in this package. Returns `None` for an unknown id, so
        the service raises `NotFoundError` rather than the repository owning an
        HTTP fact.

        Takes `now` rather than reading a clock: `ra2/persistence/` may not
        import `ra2/infra/` (sw-design.md §1.1), the same reason
        `upsert_feature` is handed `new_id`.
        """
        stored = await self._session.get(Mismatch, mismatch_id)
        if stored is None:
            return None
        stored.analyst_tag = tag
        stored.tagged_at = None if tag is None else now
        stored.note = None if tag is None else note
        await self._session.flush()
        #: Read back through the same join the list uses, so the row a handler
        #: redraws is the row the list would have drawn — one query, not a
        #: re-fetch of the page it came from.
        return await self._row(mismatch_id)

    async def _row(self, mismatch_id: MismatchId) -> MismatchListRow | None:
        one = (
            select(Mismatch, Feature.key, Record.text_anonymised_flag)
            .join(Feature, Feature.id == Mismatch.feature_id)
            .join(Record, Record.id == Mismatch.record_id)
            .where(Mismatch.id == mismatch_id)
        )
        found = (await self._session.execute(one)).first()
        return None if found is None else _to_row(*found)

    async def tally_for(
        self,
        run_id: RunId,
        *,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
    ) -> Mapping[FeatureId, Mapping[str | None, int]]:
        """Stored tag values and their row counts, per feature, for one run.

        **One grouped query per run, never one per feature** (§17.4):

            SELECT feature_id, analyst_tag, COUNT(*) FROM mismatch
             WHERE run_id = ? GROUP BY feature_id, analyst_tag

        `ix_mismatch_run_id_feature_id` already covers it. The return shape is
        what `domain.mismatch.tally` takes, so the grouping survives all the
        way into the domain instead of being expanded into rows and recounted.

        Takes the same filters as `list_for` so the strip under the table and
        the table itself cannot disagree.
        """
        grouped = (
            select(Mismatch.feature_id, Mismatch.analyst_tag, func.count())
            .where(*self._filters(run_id, feature_id=feature_id, tag_state=tag_state))
            .group_by(Mismatch.feature_id, Mismatch.analyst_tag)
        )
        counts: dict[FeatureId, dict[str | None, int]] = {}
        for feature, stored_tag, rows in (await self._session.execute(grouped)).all():
            counts.setdefault(FeatureId(feature), {})[stored_tag] = rows
        return counts

    # --- the one place the filter and the order are decided ----------------
    #
    # `list_for` and `tally_for` share both, which is what makes "the strip
    # agrees with the table" a property of this module rather than a promise
    # two call sites keep independently (§17.4).

    @staticmethod
    def _filters(
        run_id: RunId,
        *,
        feature_id: FeatureId | None,
        tag_state: TagFilter,
    ) -> list[ColumnElement[bool]]:
        where: list[ColumnElement[bool]] = [Mismatch.run_id == run_id]
        if feature_id is not None:
            where.append(Mismatch.feature_id == feature_id)
        #: A stored `""` is untagged, the same rule `domain.mismatch.tally`
        #: applies — nothing writes one, and a filter that disagreed with the
        #: tally about it would put a row in the list that the strip did not
        #: count.
        untagged = or_(Mismatch.analyst_tag.is_(None), Mismatch.analyst_tag == "")
        if isinstance(tag_state, MismatchTag):
            where.append(Mismatch.analyst_tag == tag_state.value)
        elif tag_state is TagState.UNTAGGED:
            where.append(untagged)
        elif tag_state is TagState.TAGGED:
            #: **Any** tag, including one `MismatchTag` does not name — an
            #: `other` row has been reviewed, whatever the word was.
            where.append(and_(Mismatch.analyst_tag.is_not(None), Mismatch.analyst_tag != ""))
        return where

    @staticmethod
    def _order(sort_key: str, *, descending: bool) -> list[Any]:
        """C3's four keys, and **nothing that ranks "how wrong"**.

        An unknown key falls back to `feature` rather than raising: a sort is a
        rendering input, and a stale bookmark should redraw the list, not 500.
        The closed vocabulary is enforced where it can be answered to a caller
        — `MISMATCH_SORT_KEYS`, and the API's own validation.

        `Any` for the same reason `census_repo._SORT_COLUMNS` uses it: a dict
        over four differently-typed `InstrumentedAttribute`s has no common
        static type that `order_by` also accepts.
        """
        columns: dict[str, Any] = {
            "feature": Feature.key,
            "record": Mismatch.record_id,
            "tag": Mismatch.analyst_tag,
            "reviewed": Mismatch.tagged_at,
        }
        primary = columns.get(sort_key, Feature.key)
        ordered = primary.desc() if descending else primary.asc()
        #: The id is the tie-break on every order, so the sort is **total**.
        #: Without it SQLite is free to return equal rows in any order, and
        #: page 2 of a list sorted by tag could repeat a row from page 1.
        return [ordered, Mismatch.id.asc()]


def _to_row(mismatch: Mismatch, feature_key: str, anonymised: bool) -> MismatchListRow:
    """One joined `(mismatch, feature.key, record.anonymised)` triple as the
    detached row the service renders.

    A module function rather than a classmethod because it holds no session and
    knows nothing about the query that produced it — the same reason every
    other mapping helper in `persistence/` sits beside its repository instead
    of inside it.
    """
    return MismatchListRow(
        id=MismatchId(mismatch.id),
        record_id=RecordId(mismatch.record_id),
        feature_id=FeatureId(mismatch.feature_id),
        feature_key=feature_key,
        anonymised=anonymised,
        record_value=mismatch.record_value,
        extracted_value=mismatch.extracted_value,
        evidence_span=mismatch.evidence_span,
        analyst_tag=mismatch.analyst_tag,
        tagged_at=mismatch.tagged_at,
        note=mismatch.note,
    )
