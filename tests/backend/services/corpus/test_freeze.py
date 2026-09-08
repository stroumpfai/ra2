"""Freeze: blocking validation, one transaction, the census seam (§6.3)."""

import json
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import FileKind, SourceKind
from ra2.domain.findings import FindingCode, Severity
from ra2.domain.ids import DeliveryId
from ra2.domain.language import Language
from ra2.domain.parsing.headers import CANONICAL_HEADERS
from ra2.persistence.models import (
    Corpus,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    Record,
    UnfallRow,
)
from ra2.services.errors import (
    BlockingFindingsError,
    DeliveryNotAnalysedError,
    NotFoundError,
)

pytestmark = pytest.mark.backend


async def _count(session_factory: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_analyse_select_freeze_end_to_end_on_the_hazard_delivery(
    corpus_service, analysed_golden_delivery, census_materialiser, db_session_factory
):
    delivery_id = await analysed_golden_delivery()

    corpus_id = await corpus_service.freeze(delivery_id, name="hazards", description="B1 golden")

    view = await corpus_service.get(corpus_id)
    assert view.name == "hazards"
    assert view.version == 1
    # h03 rejects one of the three `unfall` rows, so two records survive.
    assert view.record_count == 2
    assert view.language_counts == {Language.FR.value: 2}
    # h09's French has already lost its cp1252-only characters upstream: zero
    # in a corpus containing French is what proves the conversion happened.
    assert view.cp1252_canary_count == 0
    assert view.is_dev_sized is True
    assert view.delivery_id == delivery_id
    assert view.locked_by_evaluations == 0

    async with db_session_factory() as session:
        records = (await session.scalars(select(Record))).all()
        assert {r.unfall_uid for r in records} == {
            "aa000000000000000000000000000001",
            "aa000000000000000000000000000003",
        }
        # `person` hangs off `objekt`, never off `record`: a two-hop join.
        assert await session.scalar(select(func.count()).select_from(ObjektRow)) == 2
        assert await session.scalar(select(func.count()).select_from(PersonRow)) == 2
        # EAV: every column of every row, empty cells included.
        assert await session.scalar(select(func.count()).select_from(UnfallRow)) == 2 * len(
            CANONICAL_HEADERS[FileKind.UNFALL]
        )
        assert await session.scalar(select(func.count()).select_from(ObjektCell)) == 2 * len(
            CANONICAL_HEADERS[FileKind.OBJEKT]
        )
        assert await session.scalar(select(func.count()).select_from(PersonCell)) == 2 * len(
            CANONICAL_HEADERS[FileKind.PERSON]
        )

    _, called_corpus_id, census = census_materialiser.only
    assert called_corpus_id == corpus_id
    assert census.record_count == 2
    assert [t.table_name for t in census.tables] == ["unfall", "objekt", "person"]
    # The canonical header, not the observed cells: a column empty in every row
    # must still reach the census at 0 % (h08, M0-D9).
    assert census.tables[0].columns == CANONICAL_HEADERS[FileKind.UNFALL]


async def test_the_import_report_carries_the_non_blocking_findings_with_their_keys(
    corpus_service, analysed_golden_delivery, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(delivery_id, name="hazards")

    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
        report = json.loads(corpus.import_report_json)

    by_code: dict[str, list[dict[str, Any]]] = {}
    for finding in report:
        by_code.setdefault(finding["code"], []).append(finding)

    assert all(f["severity"] == Severity.REPORTED.value for f in report)
    assert FindingCode.COUNT_MISMATCH_OBJ.value in by_code
    assert FindingCode.COUNT_MISMATCH_PERS.value in by_code
    assert FindingCode.TEXT_KEY_UNMATCHED.value in by_code
    assert FindingCode.CP1252_CANARY_ZERO.value in by_code
    # Every one names the offending key (§4.2.4, §12.6).
    assert by_code[FindingCode.COUNT_MISMATCH_OBJ.value][0]["key"] == (
        "aa000000000000000000000000000001"
    )
    assert by_code[FindingCode.TEXT_KEY_UNMATCHED.value][0]["key"] == (
        "aa000000000000000000000000000002"
    )


async def test_the_manifest_records_what_went_in(
    corpus_service, analysed_golden_delivery, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(delivery_id, name="hazards")

    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
        manifest = json.loads(corpus.source_file_manifest_json)
        file_ids = json.loads(corpus.source_file_ids_json)

    assert [entry["filename"] for entry in manifest] == [
        "objekt.txt",
        "person.txt",
        "text.csv",
        "unfall.txt",
    ]
    assert {entry["file_id"] for entry in manifest} == set(file_ids)
    assert all(len(entry["sha256"]) == 64 for entry in manifest)
    # Provenance, never a filename-derived fact.
    assert {entry["file_kind"] for entry in manifest} == {"unfall", "objekt", "person", "text"}


# --- blocking ---------------------------------------------------------------


async def test_a_blocking_failure_leaves_zero_corpus_rows(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    """h07: one `UnfallUid` in two cantonal sets. Blocking, nothing written."""
    delivery_id = await upload_delivery(
        "h07",
        [
            ("ag_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "ag_unfall.txt")),
            ("be_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "be_unfall.txt")),
        ],
    )
    await delivery_service.analyse(delivery_id)

    with pytest.raises(BlockingFindingsError) as refused:
        await corpus_service.freeze(delivery_id, name="dup")

    codes = {f.code for f in refused.value.findings}
    assert FindingCode.DUP_KEY_CROSS_SET in codes
    assert all(f.is_blocking for f in refused.value.findings)

    # Asserted by counting rows, not by the absence of an exception.
    assert await _count(db_session_factory, Corpus) == 0
    assert await _count(db_session_factory, Record) == 0
    assert await _count(db_session_factory, UnfallRow) == 0


async def test_an_orphan_fk_blocks_the_freeze_and_writes_nothing(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "h06",
        [
            ("unfall.txt", hazard_bytes("h06_orphan_objekt", "unfall.txt")),
            ("objekt.txt", hazard_bytes("h06_orphan_objekt", "objekt.txt")),
        ],
    )
    await delivery_service.analyse(delivery_id)

    with pytest.raises(BlockingFindingsError) as refused:
        await corpus_service.freeze(delivery_id, name="orphan")

    orphans = [f for f in refused.value.findings if f.code is FindingCode.ORPHAN_FK]
    assert [f.detail["orphan_key"] for f in orphans] == ["ff000000000000000000000000000999"]
    assert await _count(db_session_factory, Corpus) == 0


async def test_the_census_is_not_written_when_validation_blocks(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, census_materialiser
):
    delivery_id = await upload_delivery(
        "h07",
        [
            ("ag_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "ag_unfall.txt")),
            ("be_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "be_unfall.txt")),
        ],
    )
    await delivery_service.analyse(delivery_id)

    with pytest.raises(BlockingFindingsError):
        await corpus_service.freeze(delivery_id, name="dup")

    # Zero `corpus` rows **and** zero `census_*` rows (CONTRACTS.md, E6).
    assert census_materialiser.calls == []


async def test_deselecting_the_offending_file_unblocks_the_freeze(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "h07",
        [
            ("ag_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "ag_unfall.txt")),
            ("be_unfall.txt", hazard_bytes("h07_dup_uid_cross_canton", "be_unfall.txt")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    view = await delivery_service.get(delivery_id)
    offender = next(f for f in view.files if f.filename == "be_unfall.txt")

    await delivery_service.set_selected(delivery_id, offender.file_id, selected=False)
    corpus_id = await corpus_service.freeze(delivery_id, name="ag only")

    assert (await corpus_service.get(corpus_id)).record_count == 2
    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
        # Only the selected file went into the corpus.
        assert len(json.loads(corpus.source_file_ids_json)) == 1


async def test_an_unknown_header_blocks_only_while_it_is_selected(
    corpus_service, delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "h12",
        [
            ("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt")),
            ("mystery.txt", hazard_bytes("h12_unknown_header", "unknown.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)

    with pytest.raises(BlockingFindingsError) as refused:
        await corpus_service.freeze(delivery_id, name="mystery")
    assert FindingCode.UNKNOWN_HEADER in {f.code for f in refused.value.findings}

    mystery = next(
        f for f in (await delivery_service.get(delivery_id)).files if f.filename == "mystery.txt"
    )
    await delivery_service.set_selected(delivery_id, mystery.file_id, selected=False)

    corpus_id = await corpus_service.freeze(delivery_id, name="mystery")
    assert (await corpus_service.get(corpus_id)).record_count == 3


# --- preconditions ----------------------------------------------------------


async def test_freeze_before_analysis_is_refused(
    corpus_service, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt"))]
    )
    with pytest.raises(DeliveryNotAnalysedError):
        await corpus_service.freeze(delivery_id, name="too early")
    assert await _count(db_session_factory, Corpus) == 0


async def test_freeze_with_nothing_selected_is_refused(
    corpus_service, delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt"))]
    )
    await delivery_service.analyse(delivery_id)
    only = (await delivery_service.get(delivery_id)).files[0]
    await delivery_service.set_selected(delivery_id, only.file_id, selected=False)

    with pytest.raises(DeliveryNotAnalysedError):
        await corpus_service.freeze(delivery_id, name="empty")


async def test_freeze_of_an_unknown_delivery_raises_not_found(corpus_service):
    with pytest.raises(NotFoundError) as missing:
        await corpus_service.freeze(DeliveryId("nope"), name="x")
    assert missing.value.kind == "delivery"


# --- language, text and dev sizing ------------------------------------------


async def test_the_narrative_and_its_language_come_from_the_text_file(
    corpus_service, analysed_golden_delivery, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    await corpus_service.freeze(delivery_id, name="hazards")

    async with db_session_factory() as session:
        records = {r.unfall_uid: r for r in (await session.scalars(select(Record))).all()}

    first = records["aa000000000000000000000000000001"]
    assert first.text_raw.startswith("Le conducteur a perdu le controle")
    # Never inferred from the source file (§12.5, §4.5).
    assert first.language == Language.FR.value
    assert 0.0 < first.language_confidence <= 1.0
    assert first.text_anonymised_flag is False


async def test_a_record_with_no_narrative_falls_back_to_the_anonymised_column(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    """h11's text file covers one `unfall` row; the other has no narrative."""
    delivery_id = await upload_delivery(
        "h11",
        [
            ("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt")),
            ("text.csv", hazard_bytes("h11_unmatched_text_key", "text.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    await corpus_service.freeze(delivery_id, name="fallback")

    async with db_session_factory() as session:
        records = {r.unfall_uid: r for r in (await session.scalars(select(Record))).all()}

    covered = records["aa000000000000000000000000000001"]
    assert covered.text_anonymised_flag is False

    uncovered = records["aa000000000000000000000000000002"]
    # mvp-spec.md §13 requires the anonymisation marking wherever text is shown.
    assert uncovered.text_anonymised_flag is True
    assert uncovered.text_raw == "Fahrzeug A bremste, Fahrzeug B fuhr auf."


async def test_is_dev_sized_comes_from_the_settings_floor(
    corpus_service, analysed_golden_delivery, run_upgrade_head, db_session_factory
):
    assert run_upgrade_head.dev_record_max == 50
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(delivery_id, name="hazards")

    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
    assert corpus.record_count < run_upgrade_head.dev_record_max
    assert corpus.is_dev_sized is True


async def test_the_canary_stays_silent_without_french(
    corpus_service, delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    """Zero in a German-only corpus is not evidence, so no finding (§4.4)."""
    delivery_id = await upload_delivery(
        "de",
        [
            ("unfall.txt", hazard_bytes("h11_unmatched_text_key", "unfall.txt")),
            ("text.csv", hazard_bytes("h11_unmatched_text_key", "text.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    corpus_id = await corpus_service.freeze(delivery_id, name="german")

    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
    codes = {f["code"] for f in json.loads(corpus.import_report_json)}
    assert corpus.cp1252_canary_count == 0
    assert FindingCode.CP1252_CANARY_ZERO.value not in codes
    assert Language.FR.value not in json.loads(corpus.language_counts_json)


async def test_a_re_freeze_adds_a_version_and_never_mutates_the_first(
    corpus_service, analysed_golden_delivery, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    first = await corpus_service.freeze(delivery_id, name="hazards")
    second = await corpus_service.freeze(delivery_id, name="hazards")

    assert first != second
    assert (await corpus_service.get(first)).version == 1
    assert (await corpus_service.get(second)).version == 2
    # A re-run adds rows; it never mutates a corpus (§12.2).
    assert await _count(db_session_factory, Corpus) == 2
    assert await _count(db_session_factory, Record) == 4


async def test_freeze_reads_a_host_path_delivery_in_place(
    corpus_service, delivery_service, hazards_dir, db_session_factory
):
    """The freeze re-reads bytes, so both intake paths must reach them.

    `CorpusService` is given no `FileStore` (its constructor is frozen), so it
    reconstructs one from `delivery.root_path` — see
    contracts/amendments/feat-m3-delivery-corpus.md. This is the test that
    keeps the host-path half of that shim honest.
    """
    delivery_id = await delivery_service.register(
        "AG on disk", source_kind=SourceKind.HOST_PATH, root_path=hazards_dir / "h10_count_mismatch"
    )
    await delivery_service.analyse(delivery_id)

    corpus_id = await corpus_service.freeze(delivery_id, name="in place")

    view = await corpus_service.get(corpus_id)
    assert view.record_count == 1
    async with db_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ObjektRow)) == 2
        assert await session.scalar(select(func.count()).select_from(PersonRow)) == 2
