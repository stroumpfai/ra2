# FROZEN — see CONTRACTS.md
"""The `CensusMaterialiser` seam (plan-m0-m5.md §3.1, E6).

This is the one that lets Wave 2 run in parallel:

    `corpus_service.freeze()` calls
    `CensusMaterialiser.materialise(session, corpus_id, cells)`.
    **B1 calls it, B2 implements it, neither waits.**

It takes the *session*, not a session factory, because the census write is part
of the freeze's single all-or-nothing transaction (§6.3): a blocking failure
must leave zero `corpus` rows **and** zero `census_*` rows.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.codelist_coverage import ColumnCoverage
from ra2.domain.derivation import RecordProjection
from ra2.domain.ids import CorpusId, EvaluationId, FeatureId, RecordId, RunId, TaskId
from ra2.domain.mismatch import ReviewTally
from ra2.domain.prompt import ResolvedPrompt

__all__ = [
    "CensusInput",
    "CensusMaterialiser",
    "CensusTableInput",
    "EnumCodeTableProvider",
    "GroundTruthProvider",
    "MismatchTally",
    "PromptResolver",
    "ScoreSubmitter",
    "Scorer",
    "ScoringStatus",
]


@dataclass(frozen=True, slots=True)
class CensusTableInput:
    """Everything needed to profile one table of one corpus."""

    #: `unfall`, `objekt` or `person`.
    table_name: str
    #: The canonical header, in header order. Passed explicitly so a column
    #: empty in **every** row still appears at 0 % instead of vanishing from an
    #: EAV scan (h08, mvp-spec.md §8.6).
    columns: tuple[str, ...]
    #: Every stored cell as `(column_name, value_raw)`, values verbatim.
    cells: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CensusInput:
    """What the freeze hands the materialiser."""

    #: The corpus record count — the denominator for every populated rate.
    record_count: int
    tables: tuple[CensusTableInput, ...]


@runtime_checkable
class CensusMaterialiser(Protocol):
    """Computes the census and writes `census_column` / `census_value` /
    `census_bucket` (SD2)."""

    async def materialise(
        self,
        session: AsyncSession,
        corpus_id: CorpusId,
        cells: CensusInput,
    ) -> None:
        """Write the census inside the caller's transaction.

        Must not commit, must not open its own session: the freeze owns the
        transaction boundary.
        """
        ...


@runtime_checkable
class EnumCodeTableProvider(Protocol):
    """Feature validation needs a mapped column's coverage without
    `feature_service` depending on `codelist_service` directly.

    Declared here at M9 (plan-phase-2.md §3), the same reasoning as
    `CensusMaterialiser`: E1 (`codelist_service`) and E2 (`feature_service`)
    are built by different agents in the same wave, and this seam is what
    lets neither wait on the other. `codelist_service.coverage()` implements
    it; `feature_service` is handed one, injected, and never imports
    `codelist_service`.
    """

    async def coverage(
        self, session: AsyncSession, corpus_id: CorpusId, source_column: str
    ) -> ColumnCoverage | None:
        """`None` means no mapping at all for this column."""
        ...


@runtime_checkable
class PromptResolver(Protocol):
    """The resolved prompt for one record of one evaluation.

    Declared at M17 (plan-phase-3.md §3.1) for the third time the same trick
    is played: the run worker needs the resolved prompt per record **without
    `run_service` importing `prompt_service`**. I1 implements it,
    I3 calls it, and neither waits on the other.

    Takes the *session*, not a session factory, for the same reason
    `CensusMaterialiser` does: the worker owns the transaction boundary — one
    record, one commit (sw-design.md §15.3) — and a resolver that opened its
    own session would read outside it.

    Makes **no model call**. It is the same path both preview buttons take
    (plan-phase-3.md C4).
    """

    async def resolve(
        self,
        session: AsyncSession,
        evaluation_id: EvaluationId,
        record_id: RecordId,
    ) -> ResolvedPrompt: ...


# ---------------------------------------------------------------------------
# Phase 4 (M27, plan-phase-4.md §3.1). The seams that let Wave 2's three
# agents build against seeded `score` rows instead of waiting on each other.
# ---------------------------------------------------------------------------


@runtime_checkable
class GroundTruthProvider(Protocol):
    """A feature's true value for every record of a corpus.

    The fourth time this trick is played, and the one that hides the most:
    resolving ground truth means reading `unfall_row` for a native feature and
    assembling a `RecordProjection` from `objekt_cell` / `person_cell` for a
    derived one. S4 implements it against the EAV tables; T1 calls it and never
    reaches into a repository's query internals.

    **One pass per feature, not one per record.** The return type is a whole
    corpus's worth of values because that is what makes the N+1 unwritable: a
    5 000-record corpus × 13 features is 13 queries, not 65 000, and S4's test
    asserts a bounded statement count rather than a wall-clock number
    (sw-design.md §16.2, R4).

    A record **absent from the mapping**, or present with a value
    `matching.is_empty` accepts, is not a labelled case and leaves that
    feature's denominator entirely (§8.6). The provider does not filter those
    out: deciding what counts is `domain.scoring.classify`'s job, and a
    provider that silently dropped them would make `n` unexplainable.
    """

    async def values_for(
        self,
        session: AsyncSession,
        corpus_id: CorpusId,
        feature_id: FeatureId,
    ) -> Mapping[RecordId, str | None]:
        """Native features: the stored cell. Derived: the evaluated catalogue."""
        ...

    async def projections_for(
        self,
        session: AsyncSession,
        corpus_id: CorpusId,
    ) -> Mapping[RecordId, RecordProjection]:
        """Every record's objekt/person cells, for the derived catalogue.

        Separate from `values_for` because one projection serves **every**
        derived feature of the corpus: reading it per feature would multiply
        the expensive half of the EAV scan by the number of derivations.
        """
        ...


@dataclass(frozen=True, slots=True)
class ScoringStatus:
    """How far a run's scoring pass has got — derived, never stored.

    There is no status column: `scored_features` is
    `COUNT(DISTINCT feature_id)` over the run's `score` rows, and
    `labelled_features` comes from the evaluation. The count that answers "how
    far did it get" is the same one that answers "where does it resume", so the
    two cannot disagree (sw-design.md §16.1, F5).

    The three states the read models must not conflate (§16.7):
    `scored_features == 0` is **not scored yet**, `0 < scored_features <
    labelled_features` is **in progress or interrupted**, and
    `labelled_features == 0` is **nothing scoreable** — which is a different
    fact from "no results" and says which.
    """

    run_id: RunId
    scored_features: int
    labelled_features: int
    #: `True` while a scoring task is in flight for this run. Polled through
    #: `GET /api/v1/tasks/{id}`, exactly as import and runs are.
    running: bool


@runtime_checkable
class Scorer(Protocol):
    """ "Is this run scored, and how far?" without `results_service` importing
    `scoring_service`.

    T1 implements it; T2 and T3 call it to choose between rendering numbers and
    rendering one of §16.7's three empty states.
    """

    async def status(self, session: AsyncSession, run_id: RunId) -> ScoringStatus: ...


@runtime_checkable
class ScoreSubmitter(Protocol):
    """ "Score this run, now that it is done" — **SD17's chain**, expressed as a
    seam so `run_service` never imports `scoring_service`.

    Separate from `Scorer` rather than a second method on it, because the two
    have different consumers and neither wants the other's surface: `Scorer` is
    a **read** the results views make to choose between numbers and an empty
    state, and this is the **write** the run worker makes once, at the moment a
    run turns `done`. The split is `GroundTruthProvider`/`Scorer`'s, one more
    time.

    Returns the task id, because scoring is polled through
    `GET /api/v1/tasks/{id}` exactly as import and runs are (sw-design.md
    §16.7) — and because the Results view's "scoring…" state has nothing to
    poll until something hands it one.

    Not `async`: it *schedules*, like `TaskRunner.submit`, and returns
    immediately. A run must not wait on its own scoring pass to finish, and the
    next model in the job must not wait on the previous one's.
    """

    def submit(self, run_id: RunId) -> TaskId: ...


# ---------------------------------------------------------------------------
# Phase 5 (M35, plan-phase-5.md §3.1). The fifth time this trick is played.
# ---------------------------------------------------------------------------


@runtime_checkable
class MismatchTally(Protocol):
    """Per-feature review counts, without `results_service` importing
    `mismatch_service`.

    The same seam as `CensusMaterialiser`, `EnumCodeTableProvider`,
    `PromptResolver` and `GroundTruthProvider`/`Scorer`: Y1 implements it, and
    any later Results surface that wants "how much of this has been reviewed"
    calls it without either module depending on the other.

    Takes the *session*, not a session factory, for the reason every protocol
    here does: the caller owns the transaction boundary.

    Keyed by **`RunId`**, because the list is one run at a time (sw-design.md
    §17.6) — a tally over two models' mismatches would be the cross-model
    agreement §16.9 defers.

    **It returns counts and nothing else.** There is deliberately no method
    here that could influence a score, and the absence *is* the contract
    (mvp-spec.md §12: "the tag never feeds back into a metric. Nothing is
    rescored"). §17.3 draws the missing edge; this protocol is where it would
    have been drawn.
    """

    async def tally(
        self, session: AsyncSession, run_id: RunId
    ) -> Mapping[FeatureId, ReviewTally]: ...
