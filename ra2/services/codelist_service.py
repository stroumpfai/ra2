# STUB — bodies owned by E1 (feat/p2-codelist-service). Not frozen.
"""Import codelists, map corpus columns, compute coverage (sw-design.md §14).

Implements `EnumCodeTableProvider` (`services/protocols.py`) via `coverage()`
— `feature_service` (E2) is handed this class as that protocol and never
imports it directly.

**A resolved gap** (see the class docstring on `coverage()` below):
`EnumCodeTableProvider.coverage()` is frozen with no `table_name` parameter,
but `CodelistRepository.coverage_counts()` needs one to know which EAV table
to query. This module resolves it internally by looking up the corpus's
`CensusColumn` row for `(corpus_id, column_name=source_column)` — real
accident-report column names are unique per table in practice, so a single
match is the expected case. Zero or more than one match is treated as "no
coverage data" (`None`) rather than a guess.
"""

import hashlib
import io
import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.census import TypeHint
from ra2.domain.codelist_coverage import ColumnCoverage, compute_coverage
from ra2.domain.codes import CodeAttribute as DomainCodeAttribute
from ra2.domain.codes import CodeValue as DomainCodeValue
from ra2.domain.codes import validate_import
from ra2.domain.ids import CodeAttributeId, CodeTableImportId, ColumnMappingId, CorpusId, DeliveryId
from ra2.domain.language import Language
from ra2.infra.clock import Clock
from ra2.infra.filestore import FileStore
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import (
    CensusColumn,
    CodeAttribute,
    CodeTableImport,
    CodeValue,
    ColumnMapping,
)
from ra2.persistence.repositories.census_repo import CensusRepository
from ra2.persistence.repositories.codelist_repo import CodelistRepository
from ra2.persistence.session import session_scope
from ra2.services.delivery_service import dump_json
from ra2.services.errors import CodelistImportError, NotFoundError
from ra2.services.readmodels import CodeAttributeView, CodelistImportResult, ColumnMappingView

__all__ = ["CodelistService"]

#: sw-design.md §14.2: "the prompt uses the configured prompt language", but
#: `EnumCodeTableProvider.coverage()` is frozen with no language parameter
#: (there is no evaluation-setup language selector yet to supply one from).
#: German is the one language every fixture and every real attribute carries
#: (the named gap, mvp-spec.md §7, is `it`, never `de`), so it is the least
#: surprising default for the protocol-shaped call. `list_columns()` accepts
#: an explicit `language` and threads it through instead of relying on this.
_DEFAULT_LANGUAGE = Language.DE.value

#: A page large enough to exhaust a corpus's census columns (~162, sw-design.md
#: §7's own example) in one round trip; `CensusRepository` offers no unpaged
#: convenience method, so this module pages until exhausted (task note #8).
_CENSUS_PAGE_SIZE = 500


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

    # -- import (sw-design.md §14.1) -----------------------------------------

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
        # --- 1. structural validation, before anything is touched ----------
        text = content.decode("utf-8")
        parsed = validate_import(text)
        if isinstance(parsed, list):
            raise CodelistImportError(import_errors=parsed)

        # --- 2. the no-op-reupload dedupe ------------------------------------
        source_hash = hashlib.sha256(content).hexdigest()
        async with session_scope(self._session_factory) as session:
            repo = CodelistRepository(session)
            latest = await repo.get_latest_import()
            if latest is not None and latest.source_hash == source_hash:
                attributes = await repo.list_attributes(CodeTableImportId(latest.id))
                return CodelistImportResult(
                    code_table_import_id=CodeTableImportId(latest.id),
                    source_hash=latest.source_hash,
                    imported_at=latest.imported_at,
                    attribute_count=len(attributes),
                    no_change=True,
                )

            # --- 3. a new generation -----------------------------------------
            code_table_import_id = CodeTableImportId(self._ids.new_id())
            # The same `FileStore` seam as delivery intake, a different root
            # (§14.1) — `FileStore` is typed around `DeliveryId`, so this casts
            # at the call site rather than widening the frozen protocol.
            await self._upload_store.accept(
                DeliveryId(str(code_table_import_id)), filename, io.BytesIO(content)
            )

            now = self._clock.now()
            code_table_import = CodeTableImport(
                id=code_table_import_id,
                source_file=filename,
                source_hash=source_hash,
                imported_at=now,
            )
            attributes_by_key: dict[str, CodeAttribute] = {}
            for attribute in parsed.attributes:
                orm_attribute = CodeAttribute(
                    id=CodeAttributeId(self._ids.new_id()),
                    code_table_import_id=code_table_import_id,
                    key=attribute.key,
                    chapter=attribute.chapter,
                    name_json=dump_json(dict(attribute.name)),
                )
                attributes_by_key[attribute.key] = orm_attribute
            for value in parsed.values:
                attributes_by_key[value.attribute_key].values.append(
                    CodeValue(
                        id=self._ids.new_id(),
                        code=value.code,
                        label_json=dump_json(dict(value.label)),
                    )
                )
            code_table_import.attributes = list(attributes_by_key.values())

            await repo.add_import(code_table_import)
            return CodelistImportResult(
                code_table_import_id=code_table_import_id,
                source_hash=source_hash,
                imported_at=now,
                attribute_count=len(code_table_import.attributes),
                no_change=False,
            )

    # -- reads ----------------------------------------------------------------

    async def list_columns(self, corpus_id: CorpusId, *, language: str) -> list[ColumnMappingView]:
        """Every census `enum` column of this corpus, its mapping if any, and
        its coverage status in `language`."""
        async with self._session_factory() as session:
            columns = await _all_census_columns(session, corpus_id)
            enum_columns = [c for c in columns if TypeHint(c.type_hint) is TypeHint.ENUM]
            return [await self._column_view(session, c, language=language) for c in enum_columns]

    async def list_attributes(self) -> list[CodeAttributeView]:
        """Every imported attribute — the JSON-key mapping dropdown's options.

        From the **most recent** `code_table_import` only, so a stale
        generation is never offered.
        """
        async with self._session_factory() as session:
            repo = CodelistRepository(session)
            latest = await repo.get_latest_import()
            if latest is None:
                return []
            attributes = await repo.list_attributes(CodeTableImportId(latest.id))
            return [_attribute_view(a) for a in attributes]

    # -- mapping (sw-design.md §14.2) -----------------------------------------

    async def map_column(
        self, corpus_id: CorpusId, source_column: str, code_attribute_id: CodeAttributeId
    ) -> ColumnMappingView:
        """Create or repoint a mapping. Never touches `code_value` (mvp-spec §7).

        :raises NotFoundError: no such attribute.
        """
        async with session_scope(self._session_factory) as session:
            repo = CodelistRepository(session)
            attribute = await repo.get_attribute(code_attribute_id)
            if attribute is None:
                raise NotFoundError("code_attribute", code_attribute_id)

            mapping = ColumnMapping(
                id=ColumnMappingId(self._ids.new_id()),
                corpus_id=corpus_id,
                source_column=source_column,
                code_attribute_id=code_attribute_id,
                mapped_at=self._clock.now(),
            )
            await repo.set_mapping(mapping)

            census_column = await _matching_census_column(session, corpus_id, source_column)
            if census_column is None:
                raise NotFoundError("census_column", source_column)
            return await self._column_view(session, census_column)

    async def unmap_column(self, corpus_id: CorpusId, source_column: str) -> None:
        async with session_scope(self._session_factory) as session:
            await CodelistRepository(session).delete_mapping(corpus_id, source_column)

    # -- coverage (implements `EnumCodeTableProvider`) -------------------------

    async def coverage(
        self,
        session: AsyncSession,
        corpus_id: CorpusId,
        source_column: str,
        *,
        language: str = _DEFAULT_LANGUAGE,
    ) -> ColumnCoverage | None:
        """Implements `EnumCodeTableProvider`. `None` = no mapping at all.

        Runs the `GROUP BY value_raw` query sw-design.md §14.2 calls for
        directly against this column's EAV cells, then hands the plain
        result to `domain.codelist_coverage.compute_coverage`.

        Uses `session` directly — no new session, no commit — exactly like
        `CensusMaterialiser`: this may run inside a caller's (Feature
        service's) own transaction from Wave 3 on.

        `language` is a keyword-only extension beyond `EnumCodeTableProvider`'s
        frozen three-argument shape (see the module docstring): a caller going
        through the protocol gets `_DEFAULT_LANGUAGE`; `list_columns()` passes
        the analyst-configured one explicitly.
        """
        repo = CodelistRepository(session)
        mapping = await repo.get_mapping(corpus_id, source_column)
        if mapping is None:
            return None

        table_name = await _table_name_for(session, corpus_id, source_column)
        if table_name is None:
            return None

        cells = await repo.coverage_counts(
            corpus_id, table_name=table_name, source_column=source_column
        )
        attribute = await repo.get_attribute(CodeAttributeId(mapping.code_attribute_id))
        domain_attribute = _domain_attribute(attribute) if attribute is not None else None
        code_values = _domain_values(attribute) if attribute is not None else []
        return compute_coverage(cells, domain_attribute, code_values, language)

    # -- internals --------------------------------------------------------------

    async def _column_view(
        self,
        session: AsyncSession,
        census_column: CensusColumn,
        *,
        language: str = _DEFAULT_LANGUAGE,
    ) -> ColumnMappingView:
        corpus_id = CorpusId(census_column.corpus_id)
        column_name = census_column.column_name
        repo = CodelistRepository(session)
        mapping = await repo.get_mapping(corpus_id, column_name)

        mapped_attribute_view: CodeAttributeView | None = None
        coverage: ColumnCoverage | None = None
        if mapping is not None:
            attribute = await repo.get_attribute(CodeAttributeId(mapping.code_attribute_id))
            if attribute is not None:
                mapped_attribute_view = _attribute_view(attribute)
            coverage = await self.coverage(session, corpus_id, column_name, language=language)

        return ColumnMappingView(
            corpus_id=corpus_id,
            table_name=census_column.table_name,
            column_name=column_name,
            distinct_in_corpus=census_column.distinct_count,
            mapping_id=ColumnMappingId(mapping.id) if mapping is not None else None,
            mapped_attribute=mapped_attribute_view,
            coverage=coverage,
            # C5, plan-phase-2.md §2 — the "used by" cross-link is deferred
            # until a Feature actually exists to populate it.
            used_by_features=(),
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def _all_census_columns(session: AsyncSession, corpus_id: CorpusId) -> list[CensusColumn]:
    """Every `census_column` row of a corpus, across every table.

    `CensusRepository` offers filtering by `table_name`/`min_populated_rate`
    but nothing narrower, and no unpaged convenience method — so this pages
    until exhausted rather than guessing a limit large enough (task note #8).
    """
    repo = CensusRepository(session)
    collected: list[CensusColumn] = []
    offset = 0
    while True:
        page, total = await repo.list_columns(
            corpus_id,
            table_name=None,
            min_populated_rate=None,
            sort_key="column_name",
            descending=False,
            offset=offset,
            limit=_CENSUS_PAGE_SIZE,
        )
        collected.extend(page)
        offset += _CENSUS_PAGE_SIZE
        if not page or offset >= total:
            break
    return collected


async def _matching_census_column(
    session: AsyncSession, corpus_id: CorpusId, column_name: str
) -> CensusColumn | None:
    matches = [
        c for c in await _all_census_columns(session, corpus_id) if c.column_name == column_name
    ]
    return matches[0] if len(matches) == 1 else None


async def _table_name_for(
    session: AsyncSession, corpus_id: CorpusId, source_column: str
) -> str | None:
    """The resolved gap: `EnumCodeTableProvider.coverage()` has no `table_name`
    parameter, but `coverage_counts()` needs one. Looked up from the corpus's
    own `CensusColumn` row for `(corpus_id, column_name=source_column)` — real
    accident-report column names are unique per table in practice. Zero or
    more than one match means "no coverage data" (`None`), never a guess.
    """
    census_column = await _matching_census_column(session, corpus_id, source_column)
    return census_column.table_name if census_column is not None else None


def _attribute_view(attribute: CodeAttribute) -> CodeAttributeView:
    return CodeAttributeView(
        code_attribute_id=CodeAttributeId(attribute.id),
        key=attribute.key,
        chapter=attribute.chapter,
        name=json.loads(attribute.name_json),
        code_count=len(attribute.values),
    )


def _domain_attribute(attribute: CodeAttribute) -> DomainCodeAttribute:
    return DomainCodeAttribute(
        key=attribute.key, chapter=attribute.chapter, name=json.loads(attribute.name_json)
    )


def _domain_values(attribute: CodeAttribute) -> list[DomainCodeValue]:
    return [
        DomainCodeValue(
            attribute_key=attribute.key, code=value.code, label=json.loads(value.label_json)
        )
        for value in attribute.values
    ]
