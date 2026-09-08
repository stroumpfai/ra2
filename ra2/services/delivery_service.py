# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B1
"""Register, analyse, re-parse, select (sw-design.md §6.1, §6.2).

Analyse writes only to `delivery_file`. **No corpus rows.**
"""

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import DeliveryStatus, Dialect, Encoding, FileKind, SourceKind
from ra2.domain.findings import Finding, FindingCode, Severity
from ra2.domain.ids import DeliveryId, FileId, TaskId
from ra2.domain.parsing.analysis import ParsedFile, analyse_file
from ra2.domain.validation import validate_delivery
from ra2.infra.clock import Clock
from ra2.infra.filestore import FileStore
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import ProgressReporter, TaskRunner
from ra2.persistence.models import Delivery, DeliveryFile
from ra2.persistence.repositories.delivery_repo import DeliveryRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import DeliveryFileView, DeliveryView

__all__ = ["DeliveryService"]


# ---------------------------------------------------------------------------
# Finding serialisation (M0-D8)
# ---------------------------------------------------------------------------
#
# `delivery_file.findings_json` and `corpus.import_report_json` are `Text`
# columns holding an **app-serialised** JSON string, precisely so the
# application controls key order and separators and B1's golden import report
# can be asserted byte-for-byte.
#
# These live here rather than in a third module because plan-m0-m5.md §4 gives
# B1 exactly two files this wave (`delivery_service.py`, `corpus_service.py`)
# and adding a `ra2/services/_reporting.py` would be writing outside the owned
# paths. `corpus_service.py` imports them from here.

#: Compact and lossless. `ensure_ascii=False` keeps the French and German text
#: in a finding's `detail` readable in the stored report rather than escaped.
_JSON_KWARGS = {"ensure_ascii": False, "separators": (",", ":")}


def finding_to_dict(finding: Finding) -> dict[str, object]:
    """One `Finding` as a plain dict, in a fixed key order.

    `detail`'s own keys are sorted: it is assembled by several producers and
    only a total order makes the serialisation reproducible.
    """
    return {
        "code": finding.code.value,
        "severity": finding.severity.value,
        "file_id": finding.file_id,
        "key": finding.key,
        "line_no": finding.line_no,
        "detail": {name: finding.detail[name] for name in sorted(finding.detail)},
    }


def dump_findings(findings: Iterable[Finding]) -> str:
    """`list[Finding]` -> the exact string stored in a `*_json` column."""
    return json.dumps([finding_to_dict(f) for f in findings], **_JSON_KWARGS)  # type: ignore[arg-type]


def load_findings(payload: str | None) -> tuple[Finding, ...]:
    """The inverse, for the read models. `None` and `""` mean "not analysed"."""
    if not payload:
        return ()
    raw: list[dict[str, Any]] = json.loads(payload)
    findings: list[Finding] = []
    for item in raw:
        detail: dict[str, Any] = item.get("detail") or {}
        file_id = item.get("file_id")
        line_no = item.get("line_no")
        key = item.get("key")
        findings.append(
            Finding(
                code=FindingCode(str(item["code"])),
                severity=Severity(str(item["severity"])),
                file_id=FileId(str(file_id)) if file_id is not None else None,
                key=str(key) if key is not None else None,
                line_no=int(line_no) if line_no is not None else None,
                detail={str(k): str(v) for k, v in detail.items()},
            )
        )
    return tuple(findings)


def dump_json(payload: object) -> str:
    """Any manifest/counts payload, with the same separators as the findings."""
    return json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Effective settings <-> overrides
# ---------------------------------------------------------------------------


def effective_overrides(row: DeliveryFile) -> tuple[Encoding | None, Dialect | None]:
    """The analyst's overrides, recovered from a persisted `delivery_file` row.

    `delivery_file` stores the *effective* encoding/dialect alongside what
    detection said. An override is therefore not a separate flag — it is
    exactly the case where the two differ. Recovering it this way means
    re-running `analyse()` over a whole delivery never silently discards an
    override the analyst already applied to one file, and it needs no column
    the M0 schema does not have.
    """
    encoding_override: Encoding | None = None
    if row.encoding and row.encoding != row.encoding_detected:
        encoding_override = Encoding(row.encoding)

    detected = _detected_dialect(row)
    dialect_override: Dialect | None = None
    if row.delimiter:
        effective = Dialect(delimiter=row.delimiter, quote_char=row.quote_char or '"')
        if detected is None or effective != detected:
            dialect_override = effective
    return encoding_override, dialect_override


def _detected_dialect(row: DeliveryFile) -> Dialect | None:
    """`delivery_file.dialect_detected`, which is stored as serialised JSON."""
    if not row.dialect_detected:
        return None
    payload = json.loads(row.dialect_detected)
    return Dialect(delimiter=payload["delimiter"], quote_char=payload["quote_char"])


def parsed_file_for(row: DeliveryFile, data: bytes) -> ParsedFile:
    """Re-run `analyse_file` for one persisted row, honouring its overrides.

    The one place that turns a `delivery_file` row plus its bytes back into the
    `ParsedFile` the domain works with. `corpus_service.freeze()` uses it too:
    `analyse_file` is pure, so re-running it is always cheaper and safer than
    caching cells that a re-parse could invalidate.
    """
    encoding_override, dialect_override = effective_overrides(row)
    return analyse_file(
        file_id=FileId(row.id),
        filename=row.filename,
        data=data,
        encoding_override=encoding_override,
        dialect_override=dialect_override,
        selected=row.selected,
    )


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


def file_view(row: DeliveryFile) -> DeliveryFileView:
    """One detached row of the Import view's file tables.

    `file_kind`, `source_kind` and `status` are mapped onto `String` columns
    (`models.py`'s `type_annotation_map`), so SQLAlchemy hands them back as
    plain `str`. The read models are typed with the enums, so the coercion
    happens here, once, at the boundary — never with an `is` comparison against
    a value that came out of the database.
    """
    return DeliveryFileView(
        file_id=FileId(row.id),
        filename=row.filename,
        relative_path=row.relative_path,
        byte_size=row.byte_size,
        sha256=row.sha256,
        file_kind=FileKind(row.file_kind),
        set_key=row.set_key,
        canton=row.canton,
        encoding=row.encoding,
        encoding_detected=row.encoding_detected,
        delimiter=row.delimiter,
        quote_char=row.quote_char,
        row_count=row.row_count,
        ok_count=row.ok_count,
        recovered_count=row.recovered_count,
        rejected_count=row.rejected_count,
        header_ok=row.header_ok,
        selected=row.selected,
        analysed_at=row.analysed_at,
        findings=load_findings(row.findings_json),
    )


def delivery_view(delivery: Delivery, files: Sequence[DeliveryFile]) -> DeliveryView:
    return DeliveryView(
        delivery_id=DeliveryId(delivery.id),
        name=delivery.name,
        source_kind=SourceKind(delivery.source_kind),
        root_path=delivery.root_path,
        status=DeliveryStatus(delivery.status),
        created_at=delivery.created_at,
        analysed_at=delivery.analysed_at,
        files=tuple(file_view(row) for row in sorted(files, key=lambda f: f.relative_path)),
    )


@runtime_checkable
class _RootBindingStore(Protocol):
    """A `FileStore` that has to be told which host directory a delivery came
    from. `HostPathFileStore` is the one; an upload store needs nothing."""

    def bind(self, delivery_id: DeliveryId, root: Path) -> None: ...


class DeliveryService:
    """Every seam arrives through the constructor; nothing is a global (§3)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        upload_store: FileStore,
        host_path_store: FileStore,
        task_runner: TaskRunner,
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._upload_store = upload_store
        self._host_path_store = host_path_store
        self._task_runner = task_runner
        self._clock = clock
        self._ids = ids

    # --- intake (sw-design.md §6.1) ----------------------------------------

    async def register(
        self,
        name: str,
        *,
        source_kind: SourceKind,
        root_path: Path | None = None,
    ) -> DeliveryId:
        """Create the staging area. `root_path` is required for `HOST_PATH`
        and must be absent for `UPLOAD`."""
        if source_kind is SourceKind.HOST_PATH and root_path is None:
            raise ValueError("a host_path delivery needs a root_path")
        if source_kind is SourceKind.UPLOAD and root_path is not None:
            raise ValueError("an upload delivery has no root_path; files are streamed in")

        delivery_id = DeliveryId(self._ids.new_id())
        if root_path is not None and isinstance(self._host_path_store, _RootBindingStore):
            self._host_path_store.bind(delivery_id, root_path)

        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            await repo.add(
                Delivery(
                    id=delivery_id,
                    name=name,
                    created_at=self._clock.now(),
                    source_kind=source_kind,
                    root_path=root_path.as_posix() if root_path is not None else None,
                )
            )
            if source_kind is SourceKind.HOST_PATH:
                # Registered **in place, not copied** (§6.1). The rows exist
                # from registration so the Import view can list the delivery
                # before anyone has analysed it.
                for stored in await self._host_path_store.list_files(delivery_id):
                    session.add(
                        DeliveryFile(
                            id=FileId(self._ids.new_id()),
                            delivery_id=delivery_id,
                            filename=stored.filename,
                            relative_path=stored.relative_path,
                            byte_size=stored.byte_size,
                            sha256=stored.sha256,
                        )
                    )
        return delivery_id

    async def add_file(self, delivery_id: DeliveryId, filename: str, content: BinaryIO) -> FileId:
        """Upload intake. Streamed, bounded by `RA2_MAX_UPLOAD_MB`.

        Raises `ReadOnlyFileStoreError` on a host-path delivery, whose files
        are registered in place rather than received.
        """
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            store = self._store_for(delivery)

            # A host-path store refuses this itself, so the branch that would
            # decide who may accept a file does not exist here.
            stored = await store.accept(delivery_id, filename, content)

            existing = next(
                (f for f in delivery.files if f.relative_path == stored.relative_path), None
            )
            if existing is not None:
                # Re-uploading the same name replaces the bytes, so the row's
                # analysis is no longer about the file that is there now.
                existing.byte_size = stored.byte_size
                existing.sha256 = stored.sha256
                _clear_analysis(existing)
                return FileId(existing.id)

            file_id = FileId(self._ids.new_id())
            session.add(
                DeliveryFile(
                    id=file_id,
                    delivery_id=delivery_id,
                    filename=stored.filename,
                    relative_path=stored.relative_path,
                    byte_size=stored.byte_size,
                    sha256=stored.sha256,
                )
            )
            return file_id

    async def remove_file(self, delivery_id: DeliveryId, file_id: FileId) -> None:
        """The file report modal's "remove" (sw-design.md §8.3)."""
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            row = await self._require_file(repo, delivery_id, file_id)

            if SourceKind(delivery.source_kind) is SourceKind.UPLOAD:
                await self._store_for(delivery).remove(delivery_id, row.relative_path)
            # A host-path delivery never deletes the analyst's own files
            # (`HostPathFileStore.remove` refuses): "remove" drops the file
            # from the delivery, and the file itself stays where it was.
            await session.delete(row)

    # --- analyse (sw-design.md §6.2) ---------------------------------------

    async def analyse(self, delivery_id: DeliveryId) -> TaskId:
        """Analyse every file, through `TaskRunner`, with progress.

        Idempotent and re-runnable. Returns immediately; the UI polls
        `GET /api/v1/tasks/{id}`.
        """
        async with self._session_factory() as session:
            await self._require(DeliveryRepository(session), delivery_id)

        async def work(reporter: ProgressReporter) -> None:
            await self._set_status(delivery_id, DeliveryStatus.ANALYSING)
            try:
                await self._analyse_all(delivery_id, reporter)
            except Exception:
                await self._set_status(delivery_id, DeliveryStatus.FAILED)
                raise

        return self._task_runner.submit(f"analyse:{delivery_id}", work)

    async def _analyse_all(self, delivery_id: DeliveryId, reporter: ProgressReporter) -> None:
        """One transaction over every file of the delivery.

        The per-file pipeline is `analyse_file`, which is pure; everything this
        method adds is I/O and persistence. The rows it produces are kept only
        long enough to resolve set membership across files (SD6) and are then
        dropped — `delivery_file` stores the summary, never the cells.
        """
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            store = self._store_for(delivery)
            rows = await repo.list_files(delivery_id)

            total = len(rows)
            reporter.report(0, total, "analysing")

            parsed: list[ParsedFile] = []
            now = self._clock.now()
            for index, row in enumerate(rows, start=1):
                data = await store.read_bytes(delivery_id, row.relative_path)
                result = parsed_file_for(row, data)
                parsed.append(result)
                _apply_analysis(row, result, now)
                reporter.report(index, total, row.filename)

            # Set membership is a fact about *other* files, so it cannot be
            # known during per-file analysis (SD6). One cross-file pass here
            # resolves it; `freeze()` re-runs the same function for the
            # blocking checks.
            resolved = {a.file_id: a.set_key for a in validate_delivery(parsed).files}
            for row in rows:
                row.set_key = resolved.get(FileId(row.id))

            delivery.status = DeliveryStatus.ANALYSED
            delivery.analysed_at = now

    async def reparse_file(
        self,
        delivery_id: DeliveryId,
        file_id: FileId,
        *,
        encoding: Encoding | None = None,
        delimiter: str | None = None,
        quote_char: str | None = None,
    ) -> DeliveryFileView:
        """Re-run analysis for **one file alone** after an override.

        `None` means "keep what is effective now". Changes that file's row and
        no other — there is a test that asserts exactly that.
        """
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            row = await self._require_file(repo, delivery_id, file_id)

            data = await self._store_for(delivery).read_bytes(delivery_id, row.relative_path)

            encoding_override, dialect_override = effective_overrides(row)
            if encoding is not None:
                encoding_override = encoding
            if delimiter is not None or quote_char is not None:
                base = _current_dialect(row, dialect_override)
                if base is None:
                    # The file has never been analysed, so there is no "what is
                    # effective now" to keep half of. Detect it first, so an
                    # override that names only the quote character is applied
                    # rather than silently dropped.
                    base = analyse_file(
                        file_id=FileId(row.id),
                        filename=row.filename,
                        data=data,
                        encoding_override=encoding_override,
                        selected=row.selected,
                    ).analysis.dialect
                dialect_override = _merged_dialect(base, delimiter, quote_char)

            result = analyse_file(
                file_id=FileId(row.id),
                filename=row.filename,
                data=data,
                encoding_override=encoding_override,
                dialect_override=dialect_override,
                selected=row.selected,
            )
            # `set_key` is deliberately left alone: it is cross-file knowledge
            # (SD6) and re-parsing one file must touch one row. A full
            # `analyse()` re-resolves it.
            _apply_analysis(row, result, self._clock.now())
            return file_view(row)

    # --- selection ---------------------------------------------------------

    async def set_selected(
        self, delivery_id: DeliveryId, file_id: FileId, *, selected: bool
    ) -> DeliveryView:
        """Deselected files stay in the list and are excluded from the corpus.

        Returns the whole delivery so the header count and the
        "Create corpus · N records" label both recompute from one call.
        """
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            row = await self._require_file(repo, delivery_id, file_id)
            row.selected = selected
            await session.flush()
            return delivery_view(delivery, await repo.list_files(delivery_id))

    # --- reads -------------------------------------------------------------

    async def get(self, delivery_id: DeliveryId) -> DeliveryView:
        """Raises `NotFoundError`."""
        async with self._session_factory() as session:
            repo = DeliveryRepository(session)
            delivery = await self._require(repo, delivery_id)
            return delivery_view(delivery, await repo.list_files(delivery_id))

    async def list_deliveries(self) -> tuple[DeliveryView, ...]:
        async with self._session_factory() as session:
            repo = DeliveryRepository(session)
            return tuple(delivery_view(d, d.files) for d in await repo.list_all())

    # --- internals ---------------------------------------------------------

    def _store_for(self, delivery: Delivery) -> FileStore:
        """The store this delivery's files live in. Nothing downstream of the
        seam knows which intake path was used (§6.1)."""
        if SourceKind(delivery.source_kind) is SourceKind.HOST_PATH:
            return self._host_path_store
        return self._upload_store

    async def _set_status(self, delivery_id: DeliveryId, status: DeliveryStatus) -> None:
        async with session_scope(self._session_factory) as session:
            delivery = await self._require(DeliveryRepository(session), delivery_id)
            delivery.status = status

    @staticmethod
    async def _require(repo: DeliveryRepository, delivery_id: DeliveryId) -> Delivery:
        delivery = await repo.get(delivery_id)
        if delivery is None:
            raise NotFoundError("delivery", delivery_id)
        return delivery

    @staticmethod
    async def _require_file(
        repo: DeliveryRepository, delivery_id: DeliveryId, file_id: FileId
    ) -> DeliveryFile:
        row = await repo.get_file(file_id)
        if row is None or row.delivery_id != delivery_id:
            raise NotFoundError("delivery_file", file_id)
        return row


def _current_dialect(row: DeliveryFile, override: Dialect | None) -> Dialect | None:
    """What "keep what is effective now" means for this row.

    The standing override first, then the row's persisted effective settings,
    then what detection last said. `None` only for a file that has never been
    analysed at all.
    """
    if override is not None:
        return override
    if row.delimiter:
        return Dialect(delimiter=row.delimiter, quote_char=row.quote_char or '"')
    return _detected_dialect(row)


def _merged_dialect(
    base: Dialect | None,
    delimiter: str | None,
    quote_char: str | None,
) -> Dialect | None:
    """The dialect override a partial re-parse request means.

    `None` on either argument is "keep what is effective now", so the missing
    half comes from `base`. A caller that names neither, on a file with no
    base at all, gets no override — and detection runs, which is the only
    honest answer.
    """
    resolved_delimiter = delimiter or (base.delimiter if base else None)
    if not resolved_delimiter:
        return None
    resolved_quote = quote_char or (base.quote_char if base else '"')
    return Dialect(delimiter=resolved_delimiter, quote_char=resolved_quote)


def _clear_analysis(row: DeliveryFile) -> None:
    """Reset a row to "registered, not analysed". Used when the bytes change."""
    row.file_kind = FileKind.UNKNOWN
    row.set_key = None
    row.canton = None
    row.encoding = None
    row.delimiter = None
    row.quote_char = None
    row.encoding_detected = None
    row.dialect_detected = None
    row.row_count = None
    row.ok_count = 0
    row.recovered_count = 0
    row.rejected_count = 0
    row.header_ok = None
    row.findings_json = None
    row.analysed_at = None


def _apply_analysis(row: DeliveryFile, parsed: ParsedFile, now: datetime) -> None:
    """Write one `FileAnalysis` onto its `delivery_file` row.

    `delivery_file` is one of the two mutable tables in the schema, and this is
    the only function that mutates it after intake.
    """
    analysis = parsed.analysis
    row.file_kind = analysis.kind
    row.canton = analysis.canton
    row.encoding = analysis.encoding.value if analysis.encoding else None
    row.encoding_detected = analysis.encoding_detected.value if analysis.encoding_detected else None
    row.delimiter = analysis.dialect.delimiter if analysis.dialect else None
    row.quote_char = analysis.dialect.quote_char if analysis.dialect else None
    row.dialect_detected = (
        dump_json(
            {
                "delimiter": analysis.dialect_detected.delimiter,
                "quote_char": analysis.dialect_detected.quote_char,
            }
        )
        if analysis.dialect_detected
        else None
    )
    row.row_count = analysis.row_count
    row.ok_count = analysis.ok_count
    row.recovered_count = analysis.recovered_count
    row.rejected_count = analysis.rejected_count
    row.header_ok = analysis.header_ok
    row.findings_json = dump_findings(analysis.findings)
    row.analysed_at = now
