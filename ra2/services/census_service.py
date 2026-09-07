# FROZEN (constructor + signatures) — bodies owned by B2 (feat/m3-census-export)
"""Query the materialised census (sw-design.md §7, SD2).

Reads the `census_*` tables only. **Nothing here aggregates EAV cells** — that
happened once, at freeze.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId
from ra2.services.readmodels import CensusColumnView, CensusSummary, Page, SortDir

__all__ = ["CensusService"]


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
        raise NotImplementedError

    async def summary(self, corpus_id: CorpusId) -> CensusSummary:
        """The population-profile buckets and the per-table column counts."""
        raise NotImplementedError
