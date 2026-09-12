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

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.codelist_coverage import ColumnCoverage
from ra2.domain.ids import CorpusId

__all__ = ["CensusInput", "CensusMaterialiser", "CensusTableInput", "EnumCodeTableProvider"]


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
