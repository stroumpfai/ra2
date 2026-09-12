# STUB — bodies owned by D3 (feat/p2-persistence). Not frozen.
"""Codelists persistence (sw-design.md §14, mvp-spec.md §5/§7).

`code_table_import`, `code_attribute` and `code_value` are additive, never
edited in place (Do-NOT list #2): a corrected upload is a new
`code_table_import` row, and existing `column_mapping` rows are left pointing
at the old generation until an analyst re-points them. `column_mapping`
itself is sw-design.md §14.2's "only editable state Codelists introduces" —
its methods below replace a mapping in place rather than appending a row.

`coverage_counts()` is sw-design.md §14.2's deliberate, narrow exception to
"no view queries EAV directly" (§4.4): `census_value` only keeps a column's
top 20 values, which is not enough to say *every* code appearing in the
corpus has a label, so this runs a fresh `GROUP BY value_raw` over the live
EAV cells instead. `codelist_service.coverage()` (Wave 2) is the caller.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import CodeAttributeId, CodeTableImportId, ColumnMappingId, CorpusId
from ra2.persistence.models import (
    CodeAttribute,
    CodeTableImport,
    ColumnMapping,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    Record,
    UnfallRow,
)

__all__ = ["CodelistRepository"]

#: mirrors `CensusColumn.table_name` / `ra2.domain.census`'s `table_name`
#: parameter (sw-design.md §4.2): the three structured tables, never read
#: from a filename.
_EAV_TABLE_NAMES = ("unfall", "objekt", "person")


class CodelistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- code_table_import / code_attribute / code_value --------------------

    async def add_import(self, code_table_import: CodeTableImport) -> None:
        """Writes one `code_table_import` plus its `code_attribute` and
        `code_value` children in one flush (sw-design.md §14.1 step 3) — the
        children are attached through `CodeTableImport.attributes` /
        `CodeAttribute.values`, both `cascade="all, delete-orphan"`."""
        self._session.add(code_table_import)
        await self._session.flush()

    async def get_import(self, code_table_import_id: CodeTableImportId) -> CodeTableImport | None:
        stmt = (
            select(CodeTableImport)
            .where(CodeTableImport.id == code_table_import_id)
            .options(selectinload(CodeTableImport.attributes).selectinload(CodeAttribute.values))
        )
        result: CodeTableImport | None = await self._session.scalar(stmt)
        return result

    async def list_imports(self) -> list[CodeTableImport]:
        stmt = select(CodeTableImport).order_by(CodeTableImport.imported_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_latest_import(self) -> CodeTableImport | None:
        """The most recently uploaded generation — sw-design.md §14.1 step 2's
        no-op-reupload dedupe compares a new file's hash against this one's
        `source_hash`."""
        stmt = select(CodeTableImport).order_by(CodeTableImport.imported_at.desc()).limit(1)
        result: CodeTableImport | None = await self._session.scalar(stmt)
        return result

    async def get_attribute(self, code_attribute_id: CodeAttributeId) -> CodeAttribute | None:
        stmt = (
            select(CodeAttribute)
            .where(CodeAttribute.id == code_attribute_id)
            .options(selectinload(CodeAttribute.values))
        )
        attribute: CodeAttribute | None = await self._session.scalar(stmt)
        return attribute

    async def list_attributes(self, code_table_import_id: CodeTableImportId) -> list[CodeAttribute]:
        stmt = (
            select(CodeAttribute)
            .where(CodeAttribute.code_table_import_id == code_table_import_id)
            .options(selectinload(CodeAttribute.values))
            .order_by(CodeAttribute.key)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    # -- column_mapping — the one editable table (§14.2) ---------------------

    async def get_mapping(self, corpus_id: CorpusId, source_column: str) -> ColumnMapping | None:
        stmt = select(ColumnMapping).where(
            ColumnMapping.corpus_id == corpus_id, ColumnMapping.source_column == source_column
        )
        mapping: ColumnMapping | None = await self._session.scalar(stmt)
        return mapping

    async def list_mappings(self, corpus_id: CorpusId) -> list[ColumnMapping]:
        stmt = (
            select(ColumnMapping)
            .where(ColumnMapping.corpus_id == corpus_id)
            .order_by(ColumnMapping.source_column)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def set_mapping(self, mapping: ColumnMapping) -> None:
        """Insert, or re-point in place if `(corpus_id, source_column)`
        already has a mapping — "re-editable at will" (mvp-spec.md §7), never
        a second row for the same pair (the unique constraint would refuse
        that anyway)."""
        existing = await self.get_mapping(mapping.corpus_id, mapping.source_column)
        if existing is None:
            self._session.add(mapping)
        else:
            existing.code_attribute_id = mapping.code_attribute_id
            existing.mapped_at = mapping.mapped_at
        await self._session.flush()

    async def delete_mapping(self, corpus_id: CorpusId, source_column: str) -> None:
        """ "Unmap" — a no-op if no mapping exists for that pair."""
        existing = await self.get_mapping(corpus_id, source_column)
        if existing is None:
            return
        await self._session.delete(existing)
        await self._session.flush()

    async def delete_mapping_by_id(self, mapping_id: ColumnMappingId) -> None:
        stmt = select(ColumnMapping).where(ColumnMapping.id == mapping_id)
        existing = await self._session.scalar(stmt)
        if existing is None:
            return
        await self._session.delete(existing)
        await self._session.flush()

    # -- coverage (sw-design.md §14.2) ---------------------------------------

    async def coverage_counts(
        self, corpus_id: CorpusId, *, table_name: str, source_column: str
    ) -> list[tuple[str, int]]:
        """Every distinct `(value_raw, count)` pair a mapped column takes in
        one corpus, read live from the EAV cells — never from `census_value`,
        which only keeps the top 20 (sw-design.md §14.2). `table_name` is
        `unfall` | `objekt` | `person`, exactly as `CensusColumn.table_name`
        distinguishes them; never inferred from a filename (Do-NOT list #5).

        :returns: `(value_raw, count)` pairs, ordered by descending count
            then ascending value — plain tuples, not ORM rows, so this can be
            handed straight to `codelist_service.coverage()` (Wave 2) without
            leaking a session-bound object past this layer.

            Empty cells (`value_raw == ""`) are excluded, the same rule
            `compute_census` applies (mvp-spec.md §8.6: empty means *no value
            was provided*, never a code of its own) — a code review found
            this missing here, which made every enum column with any blank
            cells report a phantom "no label — not in the codelist" row.
        """
        if table_name == "unfall":
            count_col = func.count().label("cnt")
            stmt = (
                select(UnfallRow.value_raw, count_col)
                .join(Record, UnfallRow.record_id == Record.id)
                .where(
                    Record.corpus_id == corpus_id,
                    UnfallRow.column_name == source_column,
                    UnfallRow.value_raw != "",
                )
                .group_by(UnfallRow.value_raw)
                .order_by(count_col.desc(), UnfallRow.value_raw.asc())
            )
        elif table_name == "objekt":
            count_col = func.count().label("cnt")
            stmt = (
                select(ObjektCell.value_raw, count_col)
                .join(ObjektRow, ObjektCell.objekt_row_id == ObjektRow.id)
                .join(Record, ObjektRow.record_id == Record.id)
                .where(
                    Record.corpus_id == corpus_id,
                    ObjektCell.column_name == source_column,
                    ObjektCell.value_raw != "",
                )
                .group_by(ObjektCell.value_raw)
                .order_by(count_col.desc(), ObjektCell.value_raw.asc())
            )
        elif table_name == "person":
            count_col = func.count().label("cnt")
            stmt = (
                select(PersonCell.value_raw, count_col)
                .join(PersonRow, PersonCell.person_row_id == PersonRow.id)
                .join(ObjektRow, PersonRow.objekt_row_id == ObjektRow.id)
                .join(Record, ObjektRow.record_id == Record.id)
                .where(
                    Record.corpus_id == corpus_id,
                    PersonCell.column_name == source_column,
                    PersonCell.value_raw != "",
                )
                .group_by(PersonCell.value_raw)
                .order_by(count_col.desc(), PersonCell.value_raw.asc())
            )
        else:
            raise ValueError(f"table_name must be one of {_EAV_TABLE_NAMES}, got {table_name!r}")

        rows = (await self._session.execute(stmt)).all()
        return [(value_raw, int(count)) for value_raw, count in rows]

    async def record_keys_for_value(
        self, corpus_id: CorpusId, *, table_name: str, source_column: str, value_raw: str
    ) -> list[str]:
        """Every `UnfallUid` of a record carrying this exact value in this
        column — mvp-spec.md §7's "a Finding carrying the column, the value
        and **the record key**", for the one case that names it: a code with
        no counterpart at all in the mapped attribute (`CodeUsage.
        in_codelist=False`). Deliberately narrow: called only for that
        orphan case, never for every code, the same "cheap at this
        cardinality, not at record cardinality" reasoning `coverage_counts`
        itself is built on (sw-design.md §14.2).
        """
        if table_name == "unfall":
            stmt = (
                select(Record.unfall_uid)
                .join(UnfallRow, UnfallRow.record_id == Record.id)
                .where(
                    Record.corpus_id == corpus_id,
                    UnfallRow.column_name == source_column,
                    UnfallRow.value_raw == value_raw,
                )
            )
        elif table_name == "objekt":
            stmt = (
                select(Record.unfall_uid)
                .join(ObjektRow, ObjektRow.record_id == Record.id)
                .join(ObjektCell, ObjektCell.objekt_row_id == ObjektRow.id)
                .where(
                    Record.corpus_id == corpus_id,
                    ObjektCell.column_name == source_column,
                    ObjektCell.value_raw == value_raw,
                )
            )
        elif table_name == "person":
            stmt = (
                select(Record.unfall_uid)
                .join(ObjektRow, ObjektRow.record_id == Record.id)
                .join(PersonRow, PersonRow.objekt_row_id == ObjektRow.id)
                .join(PersonCell, PersonCell.person_row_id == PersonRow.id)
                .where(
                    Record.corpus_id == corpus_id,
                    PersonCell.column_name == source_column,
                    PersonCell.value_raw == value_raw,
                )
            )
        else:
            raise ValueError(f"table_name must be one of {_EAV_TABLE_NAMES}, got {table_name!r}")

        result = await self._session.scalars(stmt.order_by(Record.unfall_uid).distinct())
        return list(result.all())
