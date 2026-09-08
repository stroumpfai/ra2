"""The concrete `CensusMaterialiser` (CONTRACTS.md "The census seam", B2).

`ra2.services.protocols.CensusMaterialiser` is frozen; this is the one
implementation of it. `corpus_service.freeze()` (B1) constructs it once at
`create_app()` time and calls `.materialise()` inside the freeze's own
transaction — this class never commits and never opens its own session
(the protocol's contract, restated on the method below).

The only logic here is wiring: `ra2.domain.census.compute_census` /
`compute_buckets` are A2's already-correct, already-tested pure functions.
This class's job is to group `CensusInput.cells` per table, feed them to those
functions, mint ids for the new rows (the protocol carries no `IdFactory`, so
one is a constructor dependency here — same pattern as every other service
seam, sw-design.md §3) and hand the results to `CensusRepository.add_all`,
which is the only thing in this call chain that touches SQLAlchemy.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.census import ColumnCensus, compute_buckets, compute_census
from ra2.domain.ids import CensusColumnId, CorpusId
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import CensusBucketRow, CensusColumn, CensusValue
from ra2.persistence.repositories.census_repo import CensusRepository
from ra2.services.protocols import CensusInput

__all__ = ["RelationalCensusMaterialiser"]


class RelationalCensusMaterialiser:
    """Computes the census with `ra2.domain.census` and writes it via
    `CensusRepository`. Satisfies `ra2.services.protocols.CensusMaterialiser`
    structurally (it is a `Protocol`); nothing here subclasses it."""

    def __init__(self, *, ids: IdFactory) -> None:
        self._ids = ids

    async def materialise(
        self,
        session: AsyncSession,
        corpus_id: CorpusId,
        cells: CensusInput,
    ) -> None:
        """Write inside the caller's transaction. Never commits, never opens
        its own session — the freeze owns the transaction boundary."""
        all_columns: list[ColumnCensus] = []
        column_rows: list[CensusColumn] = []

        for table in cells.tables:
            table_columns = compute_census(
                table.table_name,
                table.cells,
                columns=table.columns,
                record_count=cells.record_count,
            )
            all_columns.extend(table_columns)
            column_rows.extend(self._to_row(corpus_id, column) for column in table_columns)

        bucket_rows = [
            CensusBucketRow(
                corpus_id=corpus_id,
                bucket_label=bucket.label.value,
                column_count=bucket.column_count,
            )
            for bucket in compute_buckets(all_columns)
        ]

        await CensusRepository(session).add_all(column_rows, bucket_rows)

    def _to_row(self, corpus_id: CorpusId, column: ColumnCensus) -> CensusColumn:
        row = CensusColumn(
            id=CensusColumnId(self._ids.new_id()),
            corpus_id=corpus_id,
            table_name=column.table_name,
            column_name=column.column_name,
            type_hint=column.type_hint,
            record_count=column.record_count,
            populated_count=column.populated_count,
            populated_rate=column.populated_rate,
            distinct_count=column.distinct_count,
            top_value_share=column.top_value_share,
            long_tail=column.long_tail,
        )
        # `CensusColumn.values` cascades ("all, delete-orphan"): assigning
        # here persists the top-20 `CensusValue` rows in the same flush
        # (mirrors `CensusRepository.add_all`'s own docstring).
        row.values = [
            CensusValue(rank=rank, value_raw=value.value_raw, count=value.count, share=value.share)
            for rank, value in enumerate(column.top_values, start=1)
        ]
        return row
