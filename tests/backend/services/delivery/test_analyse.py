"""Analyse, re-parse after an override, select (sw-design.md §6.2)."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import DeliveryStatus, Encoding, FileKind
from ra2.domain.findings import FindingCode
from ra2.domain.ids import DeliveryId, FileId
from ra2.infra.tasks import TaskStatus
from ra2.persistence.models import Corpus, DeliveryFile
from ra2.services.readmodels import DeliveryFileView

pytestmark = pytest.mark.backend


def _codes(view: DeliveryFileView) -> set[FindingCode]:
    return {f.code for f in view.findings}


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession], delivery_id: DeliveryId
) -> dict[FileId, dict[str, Any]]:
    """Every column of every `delivery_file` row, so "changed nothing else"
    can be asserted byte-for-byte rather than field by chosen field."""
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(DeliveryFile)
                .where(DeliveryFile.delivery_id == delivery_id)
                .order_by(DeliveryFile.relative_path)
            )
        ).all()
        return {
            row.id: {
                column.name: getattr(row, column.name) for column in DeliveryFile.__table__.columns
            }
            for row in rows
        }


async def test_analyse_writes_only_delivery_file_rows(
    delivery_service, upload_delivery, hazard_bytes, db_session_factory, task_runner, clock
):
    delivery_id = await upload_delivery(
        "AG",
        [
            ("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt")),
            ("objekt.txt", hazard_bytes("h10_count_mismatch", "objekt.txt")),
            ("person.txt", hazard_bytes("h10_count_mismatch", "person.txt")),
        ],
    )

    task_id = await delivery_service.analyse(delivery_id)

    progress = task_runner.progress(task_id)
    assert progress.status is TaskStatus.OK
    assert (progress.done, progress.total) == (3, 3)

    view = await delivery_service.get(delivery_id)
    assert view.status is DeliveryStatus.ANALYSED
    assert view.analysed_at is not None
    kinds = {f.filename: f.file_kind for f in view.files}
    # The header decides the kind — nothing is read from the filename (SD5).
    assert kinds == {
        "unfall.txt": FileKind.UNFALL,
        "objekt.txt": FileKind.OBJEKT,
        "person.txt": FileKind.PERSON,
    }

    # "Analyse writes only to `delivery_file`. **No corpus rows.**"
    async with db_session_factory() as session:
        assert (await session.scalars(select(Corpus))).all() == []


async def test_analyse_reports_progress_per_file(
    delivery_service, upload_delivery, hazard_bytes, task_runner
):
    delivery_id = await upload_delivery(
        "AG",
        [
            ("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt")),
            ("objekt.txt", hazard_bytes("h10_count_mismatch", "objekt.txt")),
        ],
    )
    task_id = await delivery_service.analyse(delivery_id)
    assert task_runner.progress(task_id).name == f"analyse:{delivery_id}"
    assert task_runner.progress(task_id).total == 2


async def test_analyse_resolves_the_set_key_from_fk_reachability(
    delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "AG",
        [
            ("a.txt", hazard_bytes("h10_count_mismatch", "unfall.txt")),
            ("b.txt", hazard_bytes("h10_count_mismatch", "objekt.txt")),
            ("c.txt", hazard_bytes("h10_count_mismatch", "person.txt")),
        ],
    )
    await delivery_service.analyse(delivery_id)

    view = await delivery_service.get(delivery_id)
    # The set is named from `unfall.KantonAusw` and joined by FK reachability
    # (SD6) — the filenames here deliberately say nothing.
    assert {f.set_key for f in view.files} == {"AG"}
    assert {f.canton for f in view.files if f.file_kind is FileKind.UNFALL} == {"AG"}


async def test_analyse_is_re_runnable(delivery_service, upload_delivery, hazard_bytes):
    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h03_stray_delimiter", "unfall.txt"))]
    )
    await delivery_service.analyse(delivery_id)
    first = (await delivery_service.get(delivery_id)).files[0]

    await delivery_service.analyse(delivery_id)
    second = (await delivery_service.get(delivery_id)).files[0]

    assert first == second


async def test_an_undecodable_file_fails_and_is_reported(
    delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "h02", [("unfall.txt", hazard_bytes("h02_undecodable", "unfall.txt"))]
    )
    await delivery_service.analyse(delivery_id)

    (row,) = (await delivery_service.get(delivery_id)).files
    assert FindingCode.FILE_UNDECODABLE in _codes(row)
    assert row.encoding is None
    assert row.file_kind is FileKind.UNKNOWN


async def test_a_rejected_row_is_reported_with_its_key(
    delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "h03", [("unfall.txt", hazard_bytes("h03_stray_delimiter", "unfall.txt"))]
    )
    await delivery_service.analyse(delivery_id)

    (row,) = (await delivery_service.get(delivery_id)).files
    assert row.rejected_count == 1
    rejected = [f for f in row.findings if f.code is FindingCode.ROW_REJECTED_FIELD_COUNT]
    # Never silently dropped: the key survives the JSON round trip (§12.6).
    assert [f.key for f in rejected] == ["aa000000000000000000000000000002"]


async def test_analyse_marks_the_delivery_failed_when_a_file_disappears(
    delivery_service, upload_delivery, hazard_bytes, upload_store, task_runner
):
    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt"))]
    )
    row = (await delivery_service.get(delivery_id)).files[0]
    await upload_store.remove(delivery_id, row.relative_path)

    task_id = await delivery_service.analyse(delivery_id)

    assert task_runner.progress(task_id).status is TaskStatus.FAILED
    # A failure is a recorded outcome, never a silent retry.
    assert (await delivery_service.get(delivery_id)).status is DeliveryStatus.FAILED


# --- re-parse after an override -------------------------------------------


async def test_reparse_with_an_encoding_override_changes_that_row_and_no_other(
    delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "mixed",
        [
            ("cp1252.txt", hazard_bytes("h01_cp1252", "unfall.txt")),
            ("utf8.txt", hazard_bytes("h08_all_empty_column", "unfall.txt")),
            ("text.csv", hazard_bytes("h09_fr_lossy", "text.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    before = await _snapshot(db_session_factory, delivery_id)

    target = next(
        f for f in (await delivery_service.get(delivery_id)).files if f.filename == "utf8.txt"
    )
    assert target.encoding == Encoding.UTF_8.value

    view = await delivery_service.reparse_file(
        delivery_id, target.file_id, encoding=Encoding.CP1252
    )

    assert view.encoding == Encoding.CP1252.value
    # Detection is kept alongside the effective value, so the file report modal
    # can show "detected vs. effective" (sw-design.md §8.3).
    assert view.encoding_detected == Encoding.UTF_8.value

    after = await _snapshot(db_session_factory, delivery_id)
    assert set(before) == set(after)
    changed = [file_id for file_id in before if before[file_id] != after[file_id]]
    assert changed == [target.file_id]


async def test_reparse_with_a_delimiter_override_changes_that_row_and_no_other(
    delivery_service, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "mixed",
        [
            ("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt")),
            ("text.csv", hazard_bytes("h09_fr_lossy", "text.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    before = await _snapshot(db_session_factory, delivery_id)

    target = next(
        f for f in (await delivery_service.get(delivery_id)).files if f.filename == "text.csv"
    )
    assert (target.delimiter, target.file_kind) == (";", FileKind.TEXT)

    view = await delivery_service.reparse_file(delivery_id, target.file_id, delimiter="|")

    # The wrong delimiter makes the header unreadable, which is exactly what an
    # analyst needs to see before undoing the override.
    assert view.delimiter == "|"
    assert view.file_kind is FileKind.UNKNOWN
    assert FindingCode.UNKNOWN_HEADER in _codes(view)

    after = await _snapshot(db_session_factory, delivery_id)
    changed = [file_id for file_id in before if before[file_id] != after[file_id]]
    assert changed == [target.file_id]


async def test_a_second_analyse_keeps_an_override(delivery_service, upload_delivery, hazard_bytes):
    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt"))]
    )
    await delivery_service.analyse(delivery_id)
    target = (await delivery_service.get(delivery_id)).files[0]
    await delivery_service.reparse_file(delivery_id, target.file_id, encoding=Encoding.CP1252)

    await delivery_service.analyse(delivery_id)

    # An override is recovered from "effective != detected", so re-analysing the
    # whole delivery never silently discards the analyst's correction.
    assert (await delivery_service.get(delivery_id)).files[0].encoding == Encoding.CP1252.value


async def test_reparse_keeps_the_quote_char_when_only_the_delimiter_is_given(
    delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "text", [("text.csv", hazard_bytes("h04_embedded_newline", "text.csv"))]
    )
    await delivery_service.analyse(delivery_id)
    target = (await delivery_service.get(delivery_id)).files[0]

    view = await delivery_service.reparse_file(delivery_id, target.file_id, quote_char="'")

    assert (view.delimiter, view.quote_char) == (";", "'")


# --- selection -------------------------------------------------------------


async def test_set_selected_returns_the_whole_delivery_with_the_recomputed_count(
    delivery_service, upload_delivery, hazard_bytes
):
    delivery_id = await upload_delivery(
        "AG",
        [
            ("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt")),
            ("text.csv", hazard_bytes("h09_fr_lossy", "text.csv")),
        ],
    )
    await delivery_service.analyse(delivery_id)
    view = await delivery_service.get(delivery_id)
    assert view.selected_record_count == 3

    unfall = next(f for f in view.files if f.file_kind is FileKind.UNFALL)
    after = await delivery_service.set_selected(delivery_id, unfall.file_id, selected=False)

    # Deselected files stay in the list and are excluded from the count.
    assert len(after.files) == 2
    assert after.selected_record_count == 0
    assert not next(f for f in after.files if f.file_id == unfall.file_id).selected


async def test_reparse_before_analysis_falls_back_to_detection(
    delivery_service, upload_delivery, hazard_bytes
):
    """An override on a file that has never been analysed has no "effective
    now" to keep, so detection runs and the override is applied on top."""
    delivery_id = await upload_delivery(
        "text", [("text.csv", hazard_bytes("h09_fr_lossy", "text.csv"))]
    )
    target = (await delivery_service.get(delivery_id)).files[0]
    assert target.delimiter is None

    view = await delivery_service.reparse_file(delivery_id, target.file_id, quote_char="'")

    assert (view.delimiter, view.quote_char) == (";", "'")
    assert view.file_kind is FileKind.TEXT
