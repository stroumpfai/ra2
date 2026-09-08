# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Materialised census persistence (SD2).

Reads are filtered, sorted and paged **in SQL**, because sort and page are
service-call parameters even when the dataset would fit in memory
(sw-design.md §8.4).
"""

from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.census import BUCKET_ORDER
from ra2.domain.ids import CorpusId
from ra2.persistence.models import CensusBucketRow, CensusColumn

__all__ = ["CensusRepository"]

#: `sort_key` -> the column it sorts on. Unknown keys fall back to
#: `populated_rate`, the Census table's default sort (sw-design.md §7).
_SORT_COLUMNS: dict[str, Any] = {
    "table_name": CensusColumn.table_name,
    "column_name": CensusColumn.column_name,
    "type_hint": CensusColumn.type_hint,
    "record_count": CensusColumn.record_count,
    "populated_count": CensusColumn.populated_count,
    "populated_rate": CensusColumn.populated_rate,
    "distinct_count": CensusColumn.distinct_count,
    "top_value_share": CensusColumn.top_value_share,
    "long_tail": CensusColumn.long_tail,
}


class CensusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(
        self,
        columns: list[CensusColumn],
        buckets: list[CensusBucketRow],
    ) -> None:
        #: `CensusColumn.values` cascades ("all, delete-orphan"), so a column
        #: built with its top-20 `CensusValue`s attached persists both in one
        #: flush — nothing here inserts `CensusValue` rows directly.
        self._session.add_all(columns)
        self._session.add_all(buckets)
        await self._session.flush()

    async def list_columns(
        self,
        corpus_id: CorpusId,
        *,
        table_name: str | None,
        min_populated_rate: float | None,
        sort_key: str,
        descending: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[CensusColumn], int]:
        """Returns the page and the unpaged total, in one round trip."""
        conditions: list[ColumnElement[bool]] = [CensusColumn.corpus_id == corpus_id]
        if table_name is not None:
            conditions.append(CensusColumn.table_name == table_name)
        if min_populated_rate is not None:
            conditions.append(CensusColumn.populated_rate >= min_populated_rate)

        count_stmt = select(func.count()).select_from(CensusColumn).where(*conditions)
        total = await self._session.scalar(count_stmt) or 0

        sort_column = _SORT_COLUMNS.get(sort_key, CensusColumn.populated_rate)
        order = sort_column.desc() if descending else sort_column.asc()

        page_stmt = (
            select(CensusColumn)
            .where(*conditions)
            .options(selectinload(CensusColumn.values))
            .order_by(order, CensusColumn.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(page_stmt)
        return list(result.all()), total

    async def list_buckets(self, corpus_id: CorpusId) -> list[CensusBucketRow]:
        stmt = select(CensusBucketRow).where(CensusBucketRow.corpus_id == corpus_id)
        result = await self._session.scalars(stmt)
        rows = list(result.all())
        order = {label.value: i for i, label in enumerate(BUCKET_ORDER)}
        rows.sort(key=lambda row: order.get(row.bucket_label, len(order)))
        return rows

    async def count_by_table(self, corpus_id: CorpusId) -> dict[str, int]:
        """The `table · all 162` chip's counts."""
        stmt = (
            select(CensusColumn.table_name, func.count())
            .where(CensusColumn.corpus_id == corpus_id)
            .group_by(CensusColumn.table_name)
        )
        rows = (await self._session.execute(stmt)).all()
        # `Row` unpacks like a tuple but is not one, so `dict()` cannot take
        # it directly without upsetting mypy; the comprehension is the fix.
        return {table_name: count for table_name, count in rows}  # noqa: C416
