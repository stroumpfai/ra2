"""Corpus / census / delivery-view builders shared by B2's backend tests.

Owned by B2 (`feat/m3-census-export`, `tests/fixtures/README.md`). Nothing
here is production code — no test-only branch is added to `ra2/` (§12.12);
this module exists purely so `tests/backend/services/{census,export}/**` do
not each hand-roll the same seed rows and view objects.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.findings import Finding, FindingCode, Severity
from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.persistence.models import Corpus
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import NotFoundError
from ra2.services.protocols import CensusInput, CensusTableInput
from ra2.services.readmodels import CorpusView, DeliveryFileView, DeliveryView

__all__ = [
    "NOW",
    "StubDeliveryService",
    "make_census_input",
    "make_census_table_input",
    "make_delivery_file_view",
    "make_delivery_view",
    "make_finding",
    "seed_corpus",
]

#: A fixed instant so byte-wise CSV/report assertions do not depend on the
#: wall clock (mirrors `tests/conftest.py`'s `FROZEN_NOW`).
NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


async def seed_corpus(
    session: AsyncSession,
    corpus_id: str,
    *,
    name: str | None = None,
    version: int = 1,
    record_count: int = 100,
    imported_at: datetime = NOW,
) -> Corpus:
    """Seeds the one `corpus` row every `census_*` FK needs.

    `census_column`/`census_bucket` cascade from `corpus` (ondelete=CASCADE),
    so a materialiser or repository test needs a real parent row first —
    mirrors A3's `_seed_corpus` in `tests/backend/persistence/test_census_repo.py`,
    generalised so B2's tests do not each redefine it.
    """
    corpus = Corpus(
        id=CorpusId(corpus_id),
        name=name or f"corpus {corpus_id}",
        imported_at=imported_at,
        version=version,
        source_file_manifest_json="[]",
        import_report_json="[]",
        record_count=record_count,
        is_dev_sized=False,
        cp1252_canary_count=0,
    )
    session.add(corpus)
    await session.flush()
    return corpus


def make_census_table_input(
    table_name: str,
    columns: Sequence[str],
    cells: Sequence[tuple[str, str]],
) -> CensusTableInput:
    """Thin wrapper so a test's hand-built cell list reads as data, not
    boilerplate `CensusTableInput(...)` construction."""
    return CensusTableInput(table_name=table_name, columns=tuple(columns), cells=tuple(cells))


def make_census_input(
    record_count: int,
    tables: Sequence[CensusTableInput],
) -> CensusInput:
    return CensusInput(record_count=record_count, tables=tuple(tables))


def make_finding(
    code: FindingCode,
    *,
    severity: Severity = Severity.REPORTED,
    file_id: FileId | None = None,
    key: str | None = None,
    line_no: int | None = None,
    detail: Mapping[str, str] | None = None,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        file_id=file_id,
        key=key,
        line_no=line_no,
        detail=dict(detail or {}),
    )


def make_delivery_file_view(
    file_id: str,
    *,
    filename: str = "unfall.txt",
    relative_path: str | None = None,
    byte_size: int = 0,
    sha256: str = "0" * 64,
    file_kind: FileKind = FileKind.UNFALL,
    set_key: str | None = None,
    canton: str | None = None,
    encoding: str | None = "utf-8",
    encoding_detected: str | None = "utf-8",
    delimiter: str | None = "|",
    quote_char: str | None = '"',
    row_count: int | None = 0,
    ok_count: int = 0,
    recovered_count: int = 0,
    rejected_count: int = 0,
    header_ok: bool | None = True,
    selected: bool = True,
    analysed_at: datetime | None = NOW,
    findings: Sequence[Finding] = (),
) -> DeliveryFileView:
    return DeliveryFileView(
        file_id=FileId(file_id),
        filename=filename,
        relative_path=relative_path or filename,
        byte_size=byte_size,
        sha256=sha256,
        file_kind=file_kind,
        set_key=set_key,
        canton=canton,
        encoding=encoding,
        encoding_detected=encoding_detected,
        delimiter=delimiter,
        quote_char=quote_char,
        row_count=row_count,
        ok_count=ok_count,
        recovered_count=recovered_count,
        rejected_count=rejected_count,
        header_ok=header_ok,
        selected=selected,
        analysed_at=analysed_at,
        findings=tuple(findings),
    )


def make_delivery_view(
    delivery_id: str,
    *,
    name: str = "delivery",
    source_kind: SourceKind = SourceKind.UPLOAD,
    root_path: str | None = None,
    status: DeliveryStatus = DeliveryStatus.ANALYSED,
    created_at: datetime = NOW,
    analysed_at: datetime | None = NOW,
    files: Sequence[DeliveryFileView] = (),
) -> DeliveryView:
    return DeliveryView(
        delivery_id=DeliveryId(delivery_id),
        name=name,
        source_kind=source_kind,
        root_path=root_path,
        status=status,
        created_at=created_at,
        analysed_at=analysed_at,
        files=tuple(files),
    )


class StubDeliveryService(DeliveryService):
    """A `DeliveryService` double that returns one canned `DeliveryView`.

    `DeliveryService`'s body is B1's (frozen constructor, Wave-2 body owned
    by B1 in a worktree this branch never sees — the whole point of the
    census seam, CONTRACTS.md). `ExportService.findings_csv` needs a real
    `DeliveryService`-typed instance to call `.get()` on; this exists only
    under `tests/`, never in `ra2/` (§12.12 — no test-only branch in
    production code).
    """

    def __init__(self, view: DeliveryView) -> None:
        self._view = view

    async def get(self, delivery_id: DeliveryId) -> DeliveryView:
        return self._view


def make_corpus_view(
    corpus_id: str,
    *,
    name: str = "corpus",
    version: int = 1,
    description: str | None = None,
    imported_at: datetime = NOW,
    record_count: int = 0,
    is_dev_sized: bool = False,
    cp1252_canary_count: int = 0,
    language_counts: Mapping[str, int] = MappingProxyType({}),
    delivery_id: str | None = None,
    locked_by_evaluations: int = 0,
) -> CorpusView:
    return CorpusView(
        corpus_id=CorpusId(corpus_id),
        name=name,
        version=version,
        description=description,
        imported_at=imported_at,
        record_count=record_count,
        is_dev_sized=is_dev_sized,
        cp1252_canary_count=cp1252_canary_count,
        language_counts=language_counts,
        delivery_id=DeliveryId(delivery_id) if delivery_id is not None else None,
        locked_by_evaluations=locked_by_evaluations,
    )


class StubCorpusService(CorpusService):
    """A `CorpusService` double that reads the real `Corpus` row directly.

    `CorpusService`'s body is B1's (frozen constructor, Wave-2 body owned by
    B1 in a worktree this branch never sees — the whole point of the census
    seam, CONTRACTS.md). `ExportService._corpus_version` needs a real
    `CorpusService`-typed instance to call `.get()` on; this reads the same
    `Corpus` row the real implementation would, just without B1's other
    dependencies (`census_materialiser`, `language_detector`, ...) that
    `.get()` never touches. Exists only under `tests/`, never in `ra2/`
    (§12.12 — no test-only branch in production code).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, corpus_id: CorpusId) -> CorpusView:
        async with self._session_factory() as session:
            corpus = await session.get(Corpus, corpus_id)
        if corpus is None:
            raise NotFoundError("corpus", str(corpus_id))
        return make_corpus_view(str(corpus.id), name=corpus.name, version=corpus.version)
