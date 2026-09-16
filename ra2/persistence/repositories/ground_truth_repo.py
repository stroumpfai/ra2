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

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.derivation import RecordProjection
from ra2.domain.ids import CorpusId, FeatureId, RecordId

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
        raise NotImplementedError

    async def projections_for(
        self, session: AsyncSession, corpus_id: CorpusId
    ) -> Mapping[RecordId, RecordProjection]:
        """Every record's objekt and person cells, in one pass."""
        raise NotImplementedError
