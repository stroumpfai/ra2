# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Corpus, record and EAV persistence. Write-once: no update path exists."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import CorpusId
from ra2.persistence.models import Corpus, Evaluation

__all__ = ["CorpusRepository"]


class CorpusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, corpus: Corpus) -> None:
        self._session.add(corpus)
        await self._session.flush()

    async def get(self, corpus_id: CorpusId) -> Corpus | None:
        stmt = select(Corpus).where(Corpus.id == corpus_id)
        result: Corpus | None = await self._session.scalar(stmt)
        return result

    async def list_all(self) -> list[Corpus]:
        stmt = select(Corpus).order_by(Corpus.imported_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def next_version(self, name: str) -> int:
        """Monotonic per corpus name — the design's "v1"."""
        stmt = select(func.max(Corpus.version)).where(Corpus.name == name)
        current_max = await self._session.scalar(stmt)
        return (current_max or 0) + 1

    async def count_citing_evaluations(self, corpus_id: CorpusId) -> int:
        """Drives the `LOCKED · N eval` pill and the 409 on delete (§6.3)."""
        stmt = select(func.count()).select_from(Evaluation).where(Evaluation.corpus_id == corpus_id)
        count = await self._session.scalar(stmt)
        return int(count or 0)

    async def delete(self, corpus_id: CorpusId) -> None:
        """Only ever reached after the guard says no evaluation cites it."""
        corpus = await self.get(corpus_id)
        if corpus is None:
            return
        await self._session.delete(corpus)
        await self._session.flush()
