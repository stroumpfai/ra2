# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Materialised census persistence (SD2).

Reads are filtered, sorted and paged **in SQL**, because sort and page are
service-call parameters even when the dataset would fit in memory
(sw-design.md §8.4).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import CorpusId
from ra2.persistence.models import CensusBucketRow, CensusColumn

__all__ = ["CensusRepository"]


class CensusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(
        self,
        columns: list[CensusColumn],
        buckets: list[CensusBucketRow],
    ) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

    async def list_buckets(self, corpus_id: CorpusId) -> list[CensusBucketRow]:
        raise NotImplementedError

    async def count_by_table(self, corpus_id: CorpusId) -> dict[str, int]:
        """The `table · all 162` chip's counts."""
        raise NotImplementedError
