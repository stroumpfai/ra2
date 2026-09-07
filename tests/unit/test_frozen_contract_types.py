"""The little behaviour the M0 contract types actually carry.

Everything else at M0 is a signature. These six properties are not — they are
the derived values sw-design.md §8.1 forbids a view from computing, so they
live on the frozen types and are tested here.

Owned by the lead alongside `tests/test_m0_contract.py`; Wave 1 agents add
their own files beside it rather than editing this one.
"""

from datetime import UTC, datetime

import pytest

from ra2.domain.delivery import (
    DeliveryAnalysis,
    DeliveryStatus,
    Dialect,
    Encoding,
    FileAnalysis,
    FileKind,
    SourceKind,
)
from ra2.domain.findings import DEFAULT_SEVERITY, Finding, FindingCode, Severity
from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.services.readmodels import CorpusView, DeliveryFileView, DeliveryView

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


def _finding(code: FindingCode, **kwargs: object) -> Finding:
    return Finding(code=code, severity=DEFAULT_SEVERITY[code], **kwargs)  # type: ignore[arg-type]


def _file_analysis(*findings: Finding) -> FileAnalysis:
    return FileAnalysis(
        file_id=FileId("f1"),
        filename="whatever.txt",
        kind=FileKind.UNFALL,
        encoding_detected=Encoding.UTF_8,
        dialect_detected=Dialect(delimiter="|"),
        encoding=Encoding.UTF_8,
        dialect=Dialect(delimiter="|"),
        findings=findings,
    )


def _delivery_file(*, selected: bool, kind: FileKind, ok_count: int) -> DeliveryFileView:
    return DeliveryFileView(
        file_id=FileId("f"),
        filename="x",
        relative_path="x",
        byte_size=1,
        sha256="0" * 64,
        file_kind=kind,
        set_key=None,
        canton=None,
        encoding="utf-8",
        encoding_detected="utf-8",
        delimiter="|",
        quote_char='"',
        row_count=ok_count,
        ok_count=ok_count,
        recovered_count=0,
        rejected_count=0,
        header_ok=True,
        selected=selected,
        analysed_at=NOW,
    )


# --- findings --------------------------------------------------------------


def test_finding_defaults_to_an_empty_detail_not_a_shared_dict():
    a = Finding(code=FindingCode.ROW_RECOVERED, severity=Severity.REPORTED)
    b = Finding(code=FindingCode.ROW_RECOVERED, severity=Severity.REPORTED)
    a.detail["k"] = "v"
    assert b.detail == {}


def test_is_blocking_follows_severity_not_the_code():
    """`UNKNOWN_HEADER` is only blocking when the file is selected, so the
    raiser passes the severity (sw-design.md §6.2.2)."""
    reported = _finding(FindingCode.UNKNOWN_HEADER)
    blocking = Finding(code=FindingCode.UNKNOWN_HEADER, severity=Severity.BLOCKING)
    assert not reported.is_blocking
    assert blocking.is_blocking


def test_every_finding_code_has_a_default_severity():
    assert set(DEFAULT_SEVERITY) == set(FindingCode)


def test_finding_codes_serialise_as_their_own_name():
    """Tests assert on the code, never on prose — so the wire value must be
    the stable identifier."""
    for code in FindingCode:
        assert code.value == code.name


# --- delivery analysis -----------------------------------------------------


def test_file_analysis_has_blocking_is_true_only_for_a_blocking_finding():
    assert not _file_analysis(_finding(FindingCode.ROW_RECOVERED)).has_blocking
    assert _file_analysis(_finding(FindingCode.FILE_UNDECODABLE)).has_blocking


def test_delivery_analysis_merges_per_file_and_cross_file_findings():
    per_file = _finding(FindingCode.ROW_REJECTED_FIELD_COUNT, key="a" * 32)
    cross_file = _finding(FindingCode.DUP_KEY_CROSS_SET, key="b" * 32)
    analysis = DeliveryAnalysis(files=(_file_analysis(per_file),), findings=(cross_file,))

    assert analysis.all_findings == (per_file, cross_file)
    assert analysis.blocking == (cross_file,)


def test_a_delivery_with_no_files_has_nothing_to_report():
    assert DeliveryAnalysis().all_findings == ()
    assert DeliveryAnalysis().blocking == ()


# --- read models -----------------------------------------------------------


def test_selected_record_count_sums_only_selected_unfall_files():
    """The "Create corpus · N records" label. Deselected files stay in the list
    and are excluded; objekt/person/text rows are not records."""
    view = DeliveryView(
        delivery_id=DeliveryId("d1"),
        name="delivery",
        source_kind=SourceKind.UPLOAD,
        root_path=None,
        status=DeliveryStatus.ANALYSED,
        created_at=NOW,
        analysed_at=NOW,
        files=(
            _delivery_file(selected=True, kind=FileKind.UNFALL, ok_count=1204),
            _delivery_file(selected=True, kind=FileKind.UNFALL, ok_count=1876),
            _delivery_file(selected=False, kind=FileKind.UNFALL, ok_count=1898),
            _delivery_file(selected=True, kind=FileKind.OBJEKT, ok_count=2981),
            _delivery_file(selected=True, kind=FileKind.TEXT, ok_count=4982),
        ),
    )
    assert view.selected_record_count == 1204 + 1876


def _corpus(locked_by: int) -> CorpusView:
    return CorpusView(
        corpus_id=CorpusId("c1"),
        name="2026-09-02",
        version=1,
        description=None,
        imported_at=NOW,
        record_count=4978,
        is_dev_sized=False,
        cp1252_canary_count=0,
        language_counts={"de": 2812, "fr": 1402, "it": 396},
        delivery_id=DeliveryId("d1"),
        locked_by_evaluations=locked_by,
    )


def test_is_locked_is_true_as_soon_as_one_evaluation_cites_the_corpus():
    assert not _corpus(0).is_locked
    assert _corpus(1).is_locked
