# STUB — bodies owned by S4 (feat/p4-persistence). Not frozen.
"""Ground truth out of the EAV tables (sw-design.md §16.2).

Implements `GroundTruthProvider` (`services/protocols.py`). Scoring compares
what the model said against what the record already held, and for a **derived**
feature that second value does not exist anywhere until something computes it —
`plan-phase-2.md` Q1's deferral, coming due.

**One pass per feature, not one per record.** A 5 000-record corpus × 13
features is 13 queries; the shape of `values_for` — a whole corpus's worth of
values at once — is what makes the N+1 unwritable. `projections_for` is
separate and read **once** for the whole corpus, because one projection serves
every derived feature and reading it per feature would multiply the expensive
half of the scan by the number of derivations.

This is `SD2`'s lesson (census materialisation) in a new place, and S4's test
asserts a **bounded statement count** rather than a wall-clock number, which
would be flaky (R4).

The evaluation itself is pure and lives in `domain/derivation.py`; this module
only assembles the `RecordProjection` it takes.
"""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.derivation import RecordProjection, evaluate
from ra2.domain.feature import derivation_from_json
from ra2.domain.ids import CorpusId, FeatureId, RecordId
from ra2.persistence.models import (
    Feature,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    Record,
    UnfallRow,
)

__all__ = ["GroundTruthRepository"]


class GroundTruthRepository:
    """Holds **no session**: every `GroundTruthProvider` method takes one per
    call, because the scoring pass owns the transaction boundary — one
    `(run, feature)`, one commit (§16.1) — and a provider that opened its own
    would read outside it. Same shape `CensusMaterialiser` has, for the same
    reason."""

    async def values_for(
        self, session: AsyncSession, corpus_id: CorpusId, feature_id: FeatureId
    ) -> Mapping[RecordId, str | None]:
        """`GroundTruthProvider`. Native: the stored `unfall_row` cell.
        Derived: `domain.derivation.evaluate` over the record's projection.

        Records absent from the result, and records whose value
        `matching.is_empty` accepts, are not labelled cases and leave the
        denominator (§8.6) — but this method does **not** filter them out.
        Deciding what counts is `domain.scoring.classify`'s job, and a provider
        that silently dropped them would make `n` unexplainable.
        """
        feature = await session.get(Feature, feature_id)
        if feature is None:
            return {}

        # Branch on what the feature HAS, not on its `kind`. `kind` is stored
        # as a plain `String(16)` (M0-D7), so a reloaded row holds the string
        # `"labelled"` — equal to `Kind.LABELLED` but not identical to it, and
        # an `is` comparison here silently returned no ground truth at all.
        if feature.source_column:
            # ONE query for the whole corpus. The join is on `record`, so a
            # record with no row for this column simply does not appear —
            # which is the same thing as an empty cell for §8.6's purposes,
            # and `classify` treats them alike.
            result = await session.execute(
                select(UnfallRow.record_id, UnfallRow.value_raw)
                .join(Record, Record.id == UnfallRow.record_id)
                .where(
                    Record.corpus_id == corpus_id,
                    UnfallRow.column_name == feature.source_column,
                )
            )
            return {RecordId(record_id): value for record_id, value in result}

        if feature.derivation_json:
            # Two queries for the projections, then pure evaluation. Reading
            # them per feature would multiply the expensive half of the EAV
            # scan by the number of derivations, which is why `projections_for`
            # is separate and cacheable by the caller (§16.2).
            derivation = derivation_from_json(feature.derivation_json)
            projections = await self.projections_for(session, corpus_id)
            return {
                record_id: evaluate(derivation, projection)
                for record_id, projection in projections.items()
            }

        # An exploratory attribute, or a labelled feature with neither a source
        # column nor a derivation. Neither has ground truth: the first by
        # definition (§11.3), the second because the config is incomplete.
        return {}

    async def projections_for(
        self, session: AsyncSession, corpus_id: CorpusId
    ) -> Mapping[RecordId, RecordProjection]:
        """Every record's objekt and person cells, in one pass."""
        objekt_rows: dict[str, tuple[RecordId, dict[str, str]]] = {}
        person_rows: dict[str, tuple[RecordId, dict[str, str]]] = {}
        by_record: dict[RecordId, tuple[list[Mapping[str, str]], list[Mapping[str, str]]]] = {}

        record_ids = (
            await session.execute(select(Record.id).where(Record.corpus_id == corpus_id))
        ).scalars()
        for record_id in record_ids:
            by_record[RecordId(record_id)] = ([], [])

        # Query 1: objekt rows and their cells, outer-joined so a row with no
        # cells still exists — `count_objects` must count it.
        objekt = await session.execute(
            select(ObjektRow.id, ObjektRow.record_id, ObjektCell.column_name, ObjektCell.value_raw)
            .join(Record, Record.id == ObjektRow.record_id)
            .outerjoin(ObjektCell, ObjektCell.objekt_row_id == ObjektRow.id)
            .where(Record.corpus_id == corpus_id)
        )
        for row_id, record_id, column_name, value_raw in objekt:
            cells = objekt_rows.setdefault(row_id, (RecordId(record_id), {}))[1]
            if column_name is not None:
                cells[column_name] = value_raw

        # Query 2: person rows, reached through their parent objekt row —
        # `person` hangs off `objekt`, never off `unfall` (mvp-spec.md §4.1) —
        # and flattened per record, because no derivation crosses that edge.
        person = await session.execute(
            select(
                PersonRow.id,
                ObjektRow.record_id,
                PersonCell.column_name,
                PersonCell.value_raw,
            )
            .join(ObjektRow, ObjektRow.id == PersonRow.objekt_row_id)
            .join(Record, Record.id == ObjektRow.record_id)
            .outerjoin(PersonCell, PersonCell.person_row_id == PersonRow.id)
            .where(Record.corpus_id == corpus_id)
        )
        for row_id, record_id, column_name, value_raw in person:
            cells = person_rows.setdefault(row_id, (RecordId(record_id), {}))[1]
            if column_name is not None:
                cells[column_name] = value_raw

        for record_id, cells in objekt_rows.values():
            by_record.setdefault(record_id, ([], []))[0].append(cells)
        for record_id, cells in person_rows.values():
            by_record.setdefault(record_id, ([], []))[1].append(cells)

        return {
            record_id: RecordProjection(objekt_rows=objekt, person_rows=persons)
            for record_id, (objekt, persons) in by_record.items()
        }
