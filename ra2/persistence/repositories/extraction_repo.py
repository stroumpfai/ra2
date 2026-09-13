# STUB — bodies owned by H3 (feat/p3-persistence). Not frozen.
"""The per-record write, and the resume query (sw-design.md §15.3).

**One `extraction` row, its `extraction_value` children and its
`extraction_entity` children are committed together, per record.** `add()`
below is the whole of that: nothing here batches across records, and nothing
here holds a transaction open across an LLM call — the caller resolves the
prompt and calls the model *before* ever reaching this repository, then opens
one session, calls `add()` once, and commits.

`UNIQUE (run_id, record_id)` **is the resume key**. `pending_record_ids()` is
the read side of that constraint: "the record ids in this run's scope with no
`extraction` row" (§15.3), a query over `NOT EXISTS`, not a bookkeeping
counter. The scope itself — first `limit` corpus records by id for a dev run,
every record for a full one — is resolved *inside* the query so a hole in the
middle of an already-fixed scope is found the same way a hole at the tail is:
neither is a special case.
"""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import CorpusId, ExtractionId, RecordId, RunId
from ra2.persistence.models import Extraction, Record

__all__ = ["ExtractionRepository"]


class ExtractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, extraction: Extraction) -> None:
        """Writes one `extraction` row plus its `extraction_value` and
        `extraction_entity` children — attached through
        `Extraction.values` / `Extraction.entities` before this is called —
        in **one flush** (sw-design.md §15.3).

        `UNIQUE (run_id, record_id)` means a second call for a `(run_id,
        record_id)` pair that already has a row raises
        `sqlalchemy.exc.IntegrityError` at flush time rather than silently
        updating the existing one (Do-NOT #2) — this method does not catch
        that; a caller that wants "write if absent" must check
        `pending_record_ids()` first, which is exactly what the run worker
        does.
        """
        self._session.add(extraction)
        await self._session.flush()

    async def get(self, extraction_id: ExtractionId) -> Extraction | None:
        stmt = (
            select(Extraction)
            .where(Extraction.id == extraction_id)
            .options(selectinload(Extraction.values), selectinload(Extraction.entities))
        )
        result: Extraction | None = await self._session.scalar(stmt)
        return result

    async def get_for_record(self, run_id: RunId, record_id: RecordId) -> Extraction | None:
        stmt = (
            select(Extraction)
            .where(Extraction.run_id == run_id, Extraction.record_id == record_id)
            .options(selectinload(Extraction.values), selectinload(Extraction.entities))
        )
        result: Extraction | None = await self._session.scalar(stmt)
        return result

    async def list_for_run(self, run_id: RunId) -> list[Extraction]:
        stmt = (
            select(Extraction)
            .where(Extraction.run_id == run_id)
            .options(selectinload(Extraction.values), selectinload(Extraction.entities))
            .order_by(Extraction.record_id)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def pending_record_ids(
        self, run_id: RunId, corpus_id: CorpusId, *, limit: int | None = None
    ) -> list[RecordId]:
        """The resume set: record ids in this run's scope with no
        `extraction` row yet (sw-design.md §15.3).

        The scope is fixed **before** the "has no extraction yet" filter is
        applied: first `limit` records of `corpus_id` by id (a dev run's
        deterministic sample, §15 F9), or every record when `limit` is
        `None` (a full run). Filtering by existing extractions first and
        capping the *result* at `limit` afterwards would be wrong — once any
        of the intended records already has a row, that would silently pull
        later records into the dev scope that were never part of it. Fixing
        the scope first and then finding what is missing *inside* it is also
        what makes a hole in the middle findable at all: a record whose
        retries were exhausted mid-run leaves a gap that a simple
        "continue after the last extraction" query would miss entirely.

        :param limit: the dev cap (`RA2_DEV_RECORD_MAX`), or `None` for the
            whole corpus.
        :returns: record ids in ascending order — the same order the scope
            itself is defined in.
        """
        scope = select(Record.id).where(Record.corpus_id == corpus_id).order_by(Record.id)
        if limit is not None:
            scope = scope.limit(limit)
        scope_subquery = scope.subquery()

        stmt = (
            select(scope_subquery.c.id)
            .where(
                ~exists(
                    select(1).where(
                        Extraction.run_id == run_id,
                        Extraction.record_id == scope_subquery.c.id,
                    )
                )
            )
            .order_by(scope_subquery.c.id)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())
