# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Corpus, record and EAV persistence. Write-once: no update path exists."""

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import CorpusId
from ra2.persistence.models import Corpus

__all__ = ["CorpusRepository"]


class CorpusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, corpus: Corpus) -> None:
        raise NotImplementedError

    async def get(self, corpus_id: CorpusId) -> Corpus | None:
        raise NotImplementedError

    async def list_all(self) -> list[Corpus]:
        raise NotImplementedError

    async def next_version(self, name: str) -> int:
        """Monotonic per corpus name — the design's "v1"."""
        raise NotImplementedError

    async def count_citing_evaluations(self, corpus_id: CorpusId) -> int:
        """Drives the `LOCKED · N eval` pill and the 409 on delete (§6.3)."""
        raise NotImplementedError

    async def delete(self, corpus_id: CorpusId) -> None:
        """Only ever reached after the guard says no evaluation cites it."""
        raise NotImplementedError
