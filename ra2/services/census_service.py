# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B2
"""Query the materialised census (sw-design.md §7, SD2).

Reads the `census_*` tables only. **Nothing here aggregates EAV cells** — that
happened once, at freeze.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.census import CensusBucket, CensusBucketLabel, ValueCount
from ra2.domain.ids import CorpusId
from ra2.persistence.models import CensusColumn
from ra2.persistence.repositories.census_repo import CensusRepository
from ra2.services.readmodels import CensusColumnView, CensusSummary, Page, SortDir

__all__ = ["CensusService"]


def _to_column_view(row: CensusColumn) -> CensusColumnView:
    """The only place an ORM `CensusColumn` becomes a `CensusColumnView`.

    Every field is copied verbatim from the materialised row — nothing here
    recomputes a rate, a share or a top-values list (sw-design.md §7)."""
    return CensusColumnView(
        census_column_id=row.id,
        table_name=row.table_name,
        column_name=row.column_name,
        type_hint=row.type_hint,
        record_count=row.record_count,
        populated_count=row.populated_count,
        populated_rate=row.populated_rate,
        distinct_count=row.distinct_count,
        top_value_share=row.top_value_share,
        long_tail=row.long_tail,
        top_values=tuple(
            ValueCount(value_raw=value.value_raw, count=value.count, share=value.share)
            for value in row.values
        ),
    )


class CensusService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def columns(
        self,
        corpus_id: CorpusId,
        *,
        table_name: str | None = None,
        min_populated_rate: float | None = None,
        sort_key: str = "populated_rate",
        sort_dir: SortDir = SortDir.DESC,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[CensusColumnView]:
        """The Census table. Default sort is Populated descending.

        `table_name` and `min_populated_rate` are the two filter chips;
        changing either refilters and resets to page 1 — the caller passes
        `page=1`, the service does not remember.
        """
        offset = (page - 1) * page_size
        async with self._session_factory() as session:
            rows, total = await CensusRepository(session).list_columns(
                corpus_id,
                table_name=table_name,
                min_populated_rate=min_populated_rate,
                sort_key=sort_key,
                descending=sort_dir is SortDir.DESC,
                offset=offset,
                limit=page_size,
            )
        return Page(
            items=tuple(_to_column_view(row) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
            sort_key=sort_key,
            sort_dir=sort_dir,
        )

    async def summary(self, corpus_id: CorpusId) -> CensusSummary:
        """The population-profile buckets and the per-table column counts."""
        async with self._session_factory() as session:
            repo = CensusRepository(session)
            bucket_rows = await repo.list_buckets(corpus_id)
            counts_by_table = await repo.count_by_table(corpus_id)
        buckets = tuple(
            CensusBucket(
                label=CensusBucketLabel(bucket_row.bucket_label),
                column_count=bucket_row.column_count,
            )
            for bucket_row in bucket_rows
        )
        return CensusSummary(
            corpus_id=corpus_id,
            buckets=buckets,
            column_counts_by_table=counts_by_table,
            total_column_count=sum(counts_by_table.values()),
        )
