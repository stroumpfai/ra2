# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B1
"""Freeze a selection into an immutable corpus; list; delete-guard (§6.3)."""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.canary import canary_finding, count_canary_chars
from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.findings import Finding
from ra2.domain.ids import CorpusId, DeliveryId, ObjektRowId, PersonRowId, RecordId
from ra2.domain.language import LanguageDetector
from ra2.domain.parsing.analysis import ParsedFile
from ra2.domain.parsing.headers import (
    CANONICAL_HEADERS,
    OBJEKT_KEY_COLUMN,
    PERSON_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    TEXT_NARRATIVE_COLUMN,
    UNFALL_KEY_COLUMN,
    column_index,
)
from ra2.domain.validation import validate_delivery
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.filestore import FileStore, HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import TaskRunner
from ra2.persistence.models import (
    Corpus,
    Delivery,
    DeliveryFile,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    Record,
    UnfallRow,
)
from ra2.persistence.repositories.corpus_repo import CorpusRepository
from ra2.persistence.repositories.delivery_repo import DeliveryRepository
from ra2.persistence.session import session_scope
from ra2.services.delivery_service import dump_findings, dump_json, parsed_file_for
from ra2.services.errors import (
    BlockingFindingsError,
    CorpusLockedError,
    DeliveryNotAnalysedError,
    NotFoundError,
)
from ra2.services.protocols import CensusInput, CensusMaterialiser, CensusTableInput
from ra2.services.readmodels import CorpusView, Page, SortDir

__all__ = ["CorpusService"]

#: The `unfall` column carrying the anonymised narrative. Used only as the
#: fallback when the shared text file has no row for a record — mvp-spec.md §16
#: lists its exact semantics as an open question, so it is never preferred over
#: the delivered narrative, and a record built from it is flagged.
UNFALL_ANONYMISED_TEXT_COLUMN = "UnfHergangTextAnonym"

#: `objekt.ObjNr` / `person.PersNr` — the within-parent ordinals, kept as raw
#: text (mvp-spec.md §16 flags that role codes may or may not map onto them).
OBJEKT_ORDINAL_COLUMN = "ObjNrFeld"
PERSON_ORDINAL_COLUMN = "PersNrFeld"

#: `sort_key` -> the `CorpusView` attribute it sorts on. An unknown key falls
#: back to `imported_at`, the Corpora table's default (sw-design.md §8.4).
_SORT_KEYS: frozenset[str] = frozenset(
    {"name", "version", "imported_at", "record_count", "is_dev_sized", "cp1252_canary_count"}
)


@dataclass(frozen=True, slots=True)
class _Cell:
    """One EAV cell on its way to the census: `(column_name, value_raw)`."""

    column_name: str
    value_raw: str


def _cells_of(header: Sequence[str], row: Sequence[str]) -> Iterator[_Cell]:
    """Every cell of one delivered row, verbatim.

    Empty cells are stored: an empty string means "no value provided"
    (mvp-spec.md §8.6) and the census has to be able to count it. A row shorter
    than the header yields `""` for the tail — such a row was already rejected
    and reported, so nothing is hidden here.
    """
    for index, column in enumerate(header):
        yield _Cell(column, row[index] if index < len(row) else "")


class CorpusService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        census_materialiser: CensusMaterialiser,
        language_detector: LanguageDetector,
        task_runner: TaskRunner,
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._census_materialiser = census_materialiser
        self._language_detector = language_detector
        self._task_runner = task_runner
        self._clock = clock
        self._ids = ids
        self._settings = settings

    async def freeze(
        self,
        delivery_id: DeliveryId,
        *,
        name: str,
        description: str | None = None,
    ) -> CorpusId:
        """One transaction, all-or-nothing (sw-design.md §6.3).

        1. Cross-file **blocking** validation over the *selected* files. Any
           failure -> `BlockingFindingsError`, **nothing written**.
        2. Write `corpus`, `record` and the EAV rows.
        3. Per-record language detection; low confidence stored as `mixed`.
        4. Corpus-level cp1252 canary count. One number, no per-record markers.
        5. Non-blocking findings into `import_report_json`.
        6. The census, via `CensusMaterialiser` on this same session.
        7. `is_dev_sized` from `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN`.

        :raises BlockingFindingsError: validation refused; zero corpus rows.
        :raises DeliveryNotAnalysedError: analysis has not finished.
        """
        async with session_scope(self._session_factory) as session:
            delivery_repo = DeliveryRepository(session)
            delivery = await delivery_repo.get(delivery_id)
            if delivery is None:
                raise NotFoundError("delivery", delivery_id)
            if DeliveryStatus(delivery.status) is not DeliveryStatus.ANALYSED:
                raise DeliveryNotAnalysedError(delivery_id)

            rows = [f for f in await delivery_repo.list_files(delivery_id) if f.selected]
            if not rows or any(f.analysed_at is None for f in rows):
                raise DeliveryNotAnalysedError(delivery_id)

            # --- 1. blocking validation, before anything is written --------
            #
            # The rows are produced by re-running the *pure* `analyse_file`
            # over each selected file's bytes, honouring that file's effective
            # (possibly overridden) encoding and dialect. `delivery_file`
            # deliberately stores only the summary, so this is the single
            # source of truth for what a file's rows are and there is no cache
            # a re-parse could leave stale.
            parsed = [parsed_file_for(row, await self._read_bytes(delivery, row)) for row in rows]
            analysis = validate_delivery(parsed)
            if analysis.blocking:
                raise BlockingFindingsError(analysis.blocking)

            # --- 2-4. the corpus, its records and their cells --------------
            corpus_repo = CorpusRepository(session)
            corpus_id = CorpusId(self._ids.new_id())
            built = self._build_records(corpus_id, parsed)

            texts = [r.text_raw for r in built.records if r.text_raw]
            canary_count = count_canary_chars(texts)
            languages = {r.language for r in built.records}

            # --- 5. non-blocking findings into the import report -----------
            report: list[Finding] = [f for f in analysis.all_findings if not f.is_blocking]
            canary = canary_finding(canary_count, languages)
            if canary is not None:
                report.append(canary)

            record_count = len(built.records)
            corpus = Corpus(
                id=corpus_id,
                name=name,
                description=description,
                imported_at=self._clock.now(),
                version=await corpus_repo.next_version(name),
                source_file_manifest_json=dump_json([_manifest_entry(row) for row in rows]),
                import_report_json=dump_findings(report),
                record_count=record_count,
                # --- 7. mvp-spec.md §9 -------------------------------------
                is_dev_sized=record_count < self._settings.dev_record_max,
                cp1252_canary_count=canary_count,
                delivery_id=DeliveryId(delivery.id),
                source_file_ids_json=dump_json([row.id for row in rows]),
                language_counts_json=dump_json(_language_counts(built.records)),
            )
            corpus.records = built.records
            await corpus_repo.add(corpus)

            # --- 6. the census, on this same session and this same
            #        transaction: a blocking failure above left zero `corpus`
            #        rows and must leave zero `census_*` rows too (E6).
            await self._census_materialiser.materialise(session, corpus_id, built.census)
            return corpus_id

    async def get(self, corpus_id: CorpusId) -> CorpusView:
        """Raises `NotFoundError`."""
        async with self._session_factory() as session:
            repo = CorpusRepository(session)
            corpus = await repo.get(corpus_id)
            if corpus is None:
                raise NotFoundError("corpus", corpus_id)
            return _corpus_view(corpus, await repo.count_citing_evaluations(corpus_id))

    async def list_corpora(
        self,
        *,
        sort_key: str = "imported_at",
        sort_dir: SortDir = SortDir.DESC,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[CorpusView]:
        """Sort and page are service-call parameters, always (§8.4)."""
        key = sort_key if sort_key in _SORT_KEYS else "imported_at"
        async with self._session_factory() as session:
            repo = CorpusRepository(session)
            corpora = await repo.list_all()
            views = [
                _corpus_view(c, await repo.count_citing_evaluations(CorpusId(c.id)))
                for c in corpora
            ]

        # Sorted here rather than in SQL: `CorpusRepository` is A3's and offers
        # no paged query, and the Corpora table is a handful of rows. The
        # parameters are still the service call's, which is what §8.4 asks for.
        views.sort(key=lambda v: (getattr(v, key), v.name), reverse=sort_dir is SortDir.DESC)
        start = max(page - 1, 0) * page_size
        return Page(
            items=tuple(views[start : start + page_size]),
            total=len(views),
            page=page,
            page_size=page_size,
            sort_key=key,
            sort_dir=sort_dir,
        )

    async def delete(self, corpus_id: CorpusId) -> None:
        """Refused when any evaluation cites the corpus.

        The runs that cite it would stop being reproducible.

        :raises CorpusLockedError: -> HTTP 409, UI "delete blocked" (J3).
        """
        async with session_scope(self._session_factory) as session:
            repo = CorpusRepository(session)
            if await repo.get(corpus_id) is None:
                raise NotFoundError("corpus", corpus_id)
            citing = await repo.count_citing_evaluations(corpus_id)
            if citing > 0:
                raise CorpusLockedError(corpus_id, citing)
            await repo.delete(corpus_id)

    # --- internals ---------------------------------------------------------

    # SHIM (amendment: feat/m3-delivery-corpus) — `CorpusService.__init__` is
    # frozen and takes no `FileStore`, but the freeze has to re-read every
    # selected file's bytes to produce its rows. Rather than reach around the
    # seam, the store is **reconstructed** from state that is already
    # persisted: `settings` for an upload delivery, `delivery.root_path` for a
    # host-path one. Exact for the wired-up default and for every real
    # deployment; wrong only for a caller who injects a substitute store into
    # `create_app()`, which is what the amendment's diff fixes.
    def _store_for(self, delivery: Delivery) -> FileStore:
        if SourceKind(delivery.source_kind) is SourceKind.HOST_PATH:
            assert delivery.root_path is not None
            return HostPathFileStore({DeliveryId(delivery.id): Path(delivery.root_path)})
        return UploadedFileStore(
            self._settings.deliveries_dir, max_bytes=self._settings.max_upload_bytes
        )

    async def _read_bytes(self, delivery: Delivery, row: DeliveryFile) -> bytes:
        return await self._store_for(delivery).read_bytes(
            DeliveryId(delivery.id), row.relative_path
        )

    def _build_records(self, corpus_id: CorpusId, parsed: Sequence[ParsedFile]) -> _Built:
        """Every `record` and EAV row of the corpus, plus the census input.

        One pass over the selected files. `person` hangs off `objekt`, never
        off `record` (mvp-spec.md §4.1): person -> accident is a two-hop join,
        and getting it wrong silently changes every person-grain aggregate.
        """
        narratives = _narratives(parsed)
        objekt_by_unfall = _group(parsed, FileKind.OBJEKT, UNFALL_KEY_COLUMN)
        person_by_objekt = _group(parsed, FileKind.PERSON, OBJEKT_KEY_COLUMN)

        records: list[Record] = []
        cells: dict[str, list[tuple[str, str]]] = {
            FileKind.UNFALL.value: [],
            FileKind.OBJEKT.value: [],
            FileKind.PERSON.value: [],
        }

        for unfall_file in _of_kind(parsed, FileKind.UNFALL):
            header = unfall_file.header
            key_index = column_index(header, UNFALL_KEY_COLUMN)
            if key_index is None:  # pragma: no cover - a header mismatch blocks first
                continue
            for row in unfall_file.rows:
                unfall_uid = row[key_index] if key_index < len(row) else ""
                if not unfall_uid:
                    continue
                record_id = RecordId(self._ids.new_id())
                unfall_cells = list(_cells_of(header, row))

                # --- 3. language, per record, from the narrative (§4.5) ----
                text_raw, anonymised = _text_for(unfall_uid, unfall_cells, narratives)
                guess = self._language_detector.detect(text_raw or "")

                record = Record(
                    id=record_id,
                    corpus_id=corpus_id,
                    unfall_uid=unfall_uid,
                    language=guess.language.value,
                    language_confidence=guess.confidence,
                    text_raw=text_raw,
                    text_anonymised_flag=anonymised,
                )
                record.unfall_cells = [
                    UnfallRow(record_id=record_id, column_name=c.column_name, value_raw=c.value_raw)
                    for c in unfall_cells
                ]
                cells[FileKind.UNFALL.value].extend(
                    (c.column_name, c.value_raw) for c in unfall_cells
                )

                record.objekt_rows = self._build_objekt_rows(
                    record_id,
                    objekt_by_unfall.get(unfall_uid, ()),
                    person_by_objekt,
                    cells,
                )
                records.append(record)

        return _Built(
            records=records,
            census=CensusInput(
                record_count=len(records),
                tables=tuple(
                    CensusTableInput(
                        table_name=kind.value,
                        # The canonical header, not the observed cells: a
                        # column empty in every row must still appear at 0 %
                        # (h08, M0-D9).
                        columns=CANONICAL_HEADERS[kind],
                        cells=tuple(cells[kind.value]),
                    )
                    for kind in (FileKind.UNFALL, FileKind.OBJEKT, FileKind.PERSON)
                ),
            ),
        )

    def _build_objekt_rows(
        self,
        record_id: RecordId,
        rows: Sequence[tuple[tuple[str, ...], tuple[str, ...]]],
        person_by_objekt: dict[str, list[tuple[tuple[str, ...], tuple[str, ...]]]],
        cells: dict[str, list[tuple[str, str]]],
    ) -> list[ObjektRow]:
        built: list[ObjektRow] = []
        for header, row in rows:
            objekt_uid = _value(header, row, OBJEKT_KEY_COLUMN)
            if not objekt_uid:
                continue
            objekt_row_id = ObjektRowId(self._ids.new_id())
            objekt_cells = list(_cells_of(header, row))
            objekt = ObjektRow(
                id=objekt_row_id,
                record_id=record_id,
                objekt_uid=objekt_uid,
                obj_nr=_value(header, row, OBJEKT_ORDINAL_COLUMN) or None,
            )
            objekt.cells = [
                ObjektCell(
                    objekt_row_id=objekt_row_id, column_name=c.column_name, value_raw=c.value_raw
                )
                for c in objekt_cells
            ]
            cells[FileKind.OBJEKT.value].extend((c.column_name, c.value_raw) for c in objekt_cells)

            objekt.person_rows = self._build_person_rows(
                objekt_row_id, person_by_objekt.get(objekt_uid, ()), cells
            )
            built.append(objekt)
        return built

    def _build_person_rows(
        self,
        objekt_row_id: ObjektRowId,
        rows: Sequence[tuple[tuple[str, ...], tuple[str, ...]]],
        cells: dict[str, list[tuple[str, str]]],
    ) -> list[PersonRow]:
        built: list[PersonRow] = []
        for header, row in rows:
            person_uid = _value(header, row, PERSON_KEY_COLUMN)
            if not person_uid:
                continue
            person_row_id = PersonRowId(self._ids.new_id())
            person_cells = list(_cells_of(header, row))
            person = PersonRow(
                id=person_row_id,
                objekt_row_id=objekt_row_id,
                person_uid=person_uid,
                pers_nr=_value(header, row, PERSON_ORDINAL_COLUMN) or None,
            )
            person.cells = [
                PersonCell(
                    person_row_id=person_row_id, column_name=c.column_name, value_raw=c.value_raw
                )
                for c in person_cells
            ]
            cells[FileKind.PERSON.value].extend((c.column_name, c.value_raw) for c in person_cells)
            built.append(person)
        return built


@dataclass(frozen=True, slots=True)
class _Built:
    """What one freeze produced, before it is attached to a `Corpus`."""

    records: list[Record]
    census: CensusInput


def _of_kind(parsed: Sequence[ParsedFile], kind: FileKind) -> list[ParsedFile]:
    return [p for p in parsed if p.kind is kind]


def _value(header: Sequence[str], row: Sequence[str], column: str) -> str:
    index = column_index(header, column)
    if index is None or index >= len(row):
        return ""
    return row[index]


def _group(
    parsed: Sequence[ParsedFile], kind: FileKind, fk_column: str
) -> dict[str, list[tuple[tuple[str, ...], tuple[str, ...]]]]:
    """Rows of `kind`, grouped by their foreign key, with their own header.

    The header travels with each row because a delivery may hold several files
    of the same kind (one cantonal set each) and column order is only *usually*
    the canonical one.
    """
    grouped: dict[str, list[tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    for parsed_file in _of_kind(parsed, kind):
        header = parsed_file.header
        for parent_key, row in parsed_file.keyed(fk_column):
            if parent_key:
                grouped.setdefault(parent_key, []).append((header, row))
    return grouped


def _narratives(parsed: Sequence[ParsedFile]) -> dict[str, str]:
    """`UnfallUid` -> narrative, from the shared text file (mvp-spec.md §4.1).

    One text file covers every cantonal set, which is exactly why uniqueness is
    checked across the whole delivery before this map is built.
    """
    narratives: dict[str, str] = {}
    for text_file in _of_kind(parsed, FileKind.TEXT):
        header = text_file.header
        for key, row in text_file.keyed(TEXT_KEY_COLUMN):
            if key:
                narratives[key] = _value(header, row, TEXT_NARRATIVE_COLUMN)
    return narratives


def _text_for(
    unfall_uid: str, unfall_cells: Sequence[_Cell], narratives: dict[str, str]
) -> tuple[str | None, bool]:
    """The record's narrative, and whether it came from the anonymised column.

    The delivered text file is preferred. `unfall.UnfHergangTextAnonym` is the
    documented fallback for a record the text file does not cover, and a record
    built from it is flagged — mvp-spec.md §13 requires the anonymisation
    marking wherever text is shown.
    """
    delivered = narratives.get(unfall_uid)
    if delivered:
        return delivered, False
    for cell in unfall_cells:
        if cell.column_name.strip().casefold() == UNFALL_ANONYMISED_TEXT_COLUMN.casefold():
            return (cell.value_raw, True) if cell.value_raw else (None, False)
    return None, False


def _language_counts(records: Sequence[Record]) -> dict[str, int]:
    """The design's "de 2 812 · fr 1 402 · it 396", key-sorted for stability."""
    counts: dict[str, int] = {}
    for record in records:
        counts[record.language] = counts.get(record.language, 0) + 1
    return {language: counts[language] for language in sorted(counts)}


def _manifest_entry(row: DeliveryFile) -> dict[str, Any]:
    """One file of `corpus.source_file_manifest_json`: what went in.

    Provenance only — never a filename-derived fact. `file_kind` came from the
    header, `canton` from `unfall.KantonAusw`, `set_key` from FK reachability.
    """
    return {
        "file_id": row.id,
        "filename": row.filename,
        "relative_path": row.relative_path,
        "byte_size": row.byte_size,
        "sha256": row.sha256,
        "file_kind": FileKind(row.file_kind).value,
        "set_key": row.set_key,
        "canton": row.canton,
        "encoding": row.encoding,
        "encoding_detected": row.encoding_detected,
        "delimiter": row.delimiter,
        "quote_char": row.quote_char,
        "row_count": row.row_count,
        "ok_count": row.ok_count,
        "recovered_count": row.recovered_count,
        "rejected_count": row.rejected_count,
        "header_ok": row.header_ok,
    }


def _corpus_view(corpus: Corpus, locked_by_evaluations: int) -> CorpusView:
    counts: dict[str, int] = (
        {} if not corpus.language_counts_json else _loads(corpus.language_counts_json)
    )
    return CorpusView(
        corpus_id=CorpusId(corpus.id),
        name=corpus.name,
        version=corpus.version,
        description=corpus.description,
        imported_at=corpus.imported_at,
        record_count=corpus.record_count,
        is_dev_sized=corpus.is_dev_sized,
        cp1252_canary_count=corpus.cp1252_canary_count,
        language_counts=counts,
        delivery_id=DeliveryId(corpus.delivery_id) if corpus.delivery_id else None,
        locked_by_evaluations=locked_by_evaluations,
    )


def _loads(payload: str) -> dict[str, int]:
    parsed: dict[str, int] = json.loads(payload)
    return parsed
