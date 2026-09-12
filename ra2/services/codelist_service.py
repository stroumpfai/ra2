# STUB — bodies owned by E1 (feat/p2-codelist-service). Not frozen.
"""Import codelists, map corpus columns, compute coverage (sw-design.md §14).

Implements `EnumCodeTableProvider` (`services/protocols.py`) via `coverage()`
— `feature_service` (E2) is handed this class as that protocol and never
imports it directly.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codelist_coverage import ColumnCoverage
from ra2.domain.ids import CodeAttributeId, CorpusId
from ra2.infra.clock import Clock
from ra2.infra.filestore import FileStore
from ra2.infra.idgen import IdFactory
from ra2.services.readmodels import CodeAttributeView, CodelistImportResult, ColumnMappingView

__all__ = ["CodelistService"]


class CodelistService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        upload_store: FileStore,
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._upload_store = upload_store
        self._clock = clock
        self._ids = ids

    async def import_file(self, filename: str, content: bytes) -> CodelistImportResult:
        """sw-design.md §14.1's single transaction.

        1. Validate via `domain.codes.validate_import` — any structural error
           fails the whole import, nothing written.
        2. Hash the file; a match against the latest import is a no-op
           (`no_change=True`), not a new generation.
        3. Otherwise write one new `code_table_import` plus its attributes
           and values — additive, existing `column_mapping` rows untouched.

        :raises CodelistImportError: structural validation failed.
        """
        raise NotImplementedError

    async def list_columns(self, corpus_id: CorpusId, *, language: str) -> list[ColumnMappingView]:
        """Every census `enum` column of this corpus, its mapping if any, and
        its coverage status in `language`."""
        raise NotImplementedError

    async def list_attributes(self) -> list[CodeAttributeView]:
        """Every imported attribute — the JSON-key mapping dropdown's options."""
        raise NotImplementedError

    async def map_column(
        self, corpus_id: CorpusId, source_column: str, code_attribute_id: CodeAttributeId
    ) -> ColumnMappingView:
        """Create or repoint a mapping. Never touches `code_value` (mvp-spec §7).

        :raises NotFoundError: no such attribute.
        """
        raise NotImplementedError

    async def unmap_column(self, corpus_id: CorpusId, source_column: str) -> None:
        raise NotImplementedError

    async def coverage(
        self, session: AsyncSession, corpus_id: CorpusId, source_column: str
    ) -> ColumnCoverage | None:
        """Implements `EnumCodeTableProvider`. `None` = no mapping at all.

        Runs the `GROUP BY value_raw` query sw-design.md §14.2 calls for
        directly against this column's EAV cells, then hands the plain
        result to `domain.codelist_coverage.compute_coverage`.
        """
        raise NotImplementedError
