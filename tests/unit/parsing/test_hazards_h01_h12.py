"""One named test per hazard fixture (sw-design.md §11.4).

Each asserts **the exact `FindingCode`** and **that the offending key is in the
finding's detail**. `detail` is what the UI renders and what the CSV export
writes, so a key that reaches only `Finding.key` is a key the analyst never
sees; both are checked.

Four hazards are file-level and have no row key — h01's offending datum is an
encoding, h02's a byte, h09's a count, h12's a header. Each of those asserts the
datum that identifies *it*, for the same reason and by the same rule.

Prose is never asserted. `FindingCode` values are stable identifiers; the
wording lives in one rendering table in `ra2/ui/` (sw-design.md §5).
"""

import pytest

from ra2.domain.canary import canary_finding, count_canary_chars
from ra2.domain.delivery import Encoding, FileKind, RowOutcome
from ra2.domain.findings import FindingCode, Severity
from ra2.domain.ids import FileId
from ra2.domain.parsing.analysis import analyse_file
from ra2.domain.parsing.headers import (
    TEXT_NARRATIVE_COLUMN,
    UNFALL_KEY_COLUMN,
)
from ra2.domain.validation import blocking_findings, validate_delivery

REPLACEMENT_CHAR = "�"


# --- h01 -------------------------------------------------------------------


def test_h01_cp1252_is_detected_decoded_and_reported(hz):
    """Windows-1252 bytes: detected, decoded, reported — and never mangled."""
    parsed = hz.parse("h01_cp1252", "unfall.txt")

    assert parsed.analysis.encoding is Encoding.CP1252
    assert parsed.analysis.encoding_detected is Encoding.CP1252

    finding = hz.only(parsed.analysis.findings, FindingCode.ENCODING_DETECTED)
    assert finding.severity is Severity.REPORTED
    assert finding.detail["encoding"] == Encoding.CP1252.value

    narratives = list(parsed.values("UnfHergangTextAnonym"))
    assert any("Nässe" in n for n in narratives), narratives
    assert not any(REPLACEMENT_CHAR in n for n in narratives)


def test_h01_is_not_valid_utf8_so_the_fallback_is_really_exercised(hz):
    """If the fixture ever became valid UTF-8 the cp1252 path would stop being
    tested and this test would still pass on encoding alone. Guard the fixture."""
    with pytest.raises(UnicodeDecodeError):
        hz.bytes_of("h01_cp1252", "unfall.txt").decode("utf-8")


# --- h02 -------------------------------------------------------------------


def test_h02_undecodable_bytes_fail_the_file(hz):
    """Bytes valid in neither encoding fail the file. No `U+FFFD`, ever."""
    parsed = hz.parse("h02_undecodable", "unfall.txt")

    finding = hz.only(parsed.analysis.findings, FindingCode.FILE_UNDECODABLE)
    assert finding.severity is Severity.BLOCKING
    # The offending datum for a file-level failure is the byte itself.
    assert finding.detail["byte"] == "0x9d"
    assert int(finding.detail["byte_offset"]) > 0
    assert finding.detail["tried"] == "utf-8,cp1252"

    assert parsed.analysis.kind is FileKind.UNKNOWN
    assert parsed.analysis.encoding is None
    assert parsed.rows == ()
    assert not any(REPLACEMENT_CHAR in cell for row in parsed.rows for cell in row)


def test_h02_fails_under_an_explicit_override_too(hz):
    """An analyst overriding the encoding cannot force undecodable bytes through."""
    parsed = hz.parse("h02_undecodable", "unfall.txt", encoding_override=Encoding.CP1252)
    assert hz.only(parsed.analysis.findings, FindingCode.FILE_UNDECODABLE)


# --- h03 -------------------------------------------------------------------


def test_h03_stray_delimiter_rejects_the_row_with_its_key(hz):
    """A 68-field row under a 67-column header is rejected, never repaired."""
    parsed = hz.parse("h03_stray_delimiter", "unfall.txt")
    key = hz.uid("aa", 2)

    finding = hz.only(parsed.analysis.findings, FindingCode.ROW_REJECTED_FIELD_COUNT)
    assert finding.key == key
    assert key in hz.detail_values(finding)
    assert finding.detail["expected_fields"] == "67"
    assert finding.detail["actual_fields"] == "68"

    assert parsed.analysis.rejected_count == 1
    assert parsed.analysis.ok_count == 2
    assert parsed.analysis.recovered_count == 0
    # Detected, not repaired: the bad row is absent from the imported rows and
    # no guess about where the stray `|` landed was written anywhere.
    assert key not in set(parsed.values(UNFALL_KEY_COLUMN))


# --- h04 -------------------------------------------------------------------


def test_h04_quoted_embedded_newline_is_recovered_and_counted(hz):
    """A record spanning two physical lines is reported even when RFC4180
    quoting is what put it back together."""
    parsed = hz.parse("h04_embedded_newline", "text.csv")
    key = hz.uid("aa", 1)

    finding = hz.only(parsed.analysis.findings, FindingCode.ROW_RECOVERED)
    assert finding.key == key
    assert key in hz.detail_values(finding)
    assert finding.detail["method"] == "quoted"
    assert finding.detail["continuation_lines"] == "1"

    assert parsed.analysis.recovered_count == 1
    assert parsed.analysis.ok_count == 1
    assert parsed.analysis.rejected_count == 0

    narrative = next(iter(parsed.values(TEXT_NARRATIVE_COLUMN)))
    assert "Der Lenker bremste stark." in narrative
    assert "Anschliessend kam es zur Kollision." in narrative


# --- h05 -------------------------------------------------------------------


def test_h05_unquoted_newline_is_recovered_by_the_key_anchor(hz):
    """With no quoting to lean on, only `^[0-9A-Fa-f]{32}<delim>` can repair it."""
    parsed = hz.parse("h05_unquoted_newline", "text.csv")
    key = hz.uid("aa", 1)

    finding = hz.only(parsed.analysis.findings, FindingCode.ROW_RECOVERED)
    assert finding.key == key
    assert key in hz.detail_values(finding)
    assert finding.detail["method"] == "key_anchor"
    assert finding.detail["continuation_lines"] == "2"

    assert parsed.analysis.recovered_count == 1
    assert parsed.analysis.ok_count == 1
    narrative = next(iter(parsed.values(TEXT_NARRATIVE_COLUMN)))
    assert narrative == (
        "Der Lenker bremste stark.\n"
        "Anschliessend kam es zur Kollision.\n"
        "Der Sachschaden war erheblich."
    )


# --- h06 -------------------------------------------------------------------


def test_h06_orphan_objekt_is_blocking_and_names_the_key(hz):
    """`objekt.UnfallUid` with no parent stops the freeze."""
    analysis = validate_delivery(hz.parse_all("h06_orphan_objekt"))
    orphan_parent = hz.uid("ff", 999)
    child_key = hz.uid("aa", 12)

    finding = hz.only(analysis.findings, FindingCode.ORPHAN_FK)
    assert finding.severity is Severity.BLOCKING
    assert finding.key == child_key
    assert child_key in hz.detail_values(finding)
    assert orphan_parent in hz.detail_values(finding)
    assert finding.detail["child_table"] == FileKind.OBJEKT.value
    assert finding.detail["parent_key"] == UNFALL_KEY_COLUMN

    assert finding in blocking_findings(analysis)


# --- h07 -------------------------------------------------------------------


def test_h07_uid_duplicated_across_cantonal_sets_is_blocking(hz):
    """The collision mvp-spec.md §4.1 exists to catch: each file is internally
    unique, so only a delivery-wide check finds it."""
    files = hz.parse_all("h07_dup_uid_cross_canton")
    analysis = validate_delivery(files)
    shared = hz.uid("aa", 1)

    finding = hz.only(analysis.findings, FindingCode.DUP_KEY_CROSS_SET)
    assert finding.severity is Severity.BLOCKING
    assert finding.key == shared
    assert shared in hz.detail_values(finding)
    assert finding.detail["key_kind"] == UNFALL_KEY_COLUMN
    assert finding.detail["files"] == "ag_unfall.txt, be_unfall.txt"


def test_h07_cantons_come_from_the_data_not_the_filenames(hz):
    """`KantonAusw`, never `ag_`/`be_` in the name (§12.5)."""
    analysis = validate_delivery(hz.parse_all("h07_dup_uid_cross_canton"))
    assert {f.canton for f in analysis.files} == {"AG", "BE"}
    assert {f.set_key for f in analysis.files} == {"AG", "BE"}


def test_h07_deselecting_one_file_unblocks_the_freeze(hz):
    """Deselected files stay listed and take part in no cross-file check."""
    files = hz.parse_all("h07_dup_uid_cross_canton", be_unfall=False)
    analysis = validate_delivery(files)

    assert hz.of_code(analysis.findings, FindingCode.DUP_KEY_CROSS_SET) == []
    assert len(analysis.files) == 2  # still both listed


# --- h08 -------------------------------------------------------------------


def test_h08_all_empty_column_parses_as_present_and_empty(hz):
    """A column empty in every row must still be a column.

    The census reports it at 0 % and leaves it out of every denominator (A2,
    M0-D9). That is only possible if it survives parsing as a real column with
    empty values, rather than vanishing.
    """
    parsed = hz.parse("h08_all_empty_column", "unfall.txt")
    column = "VssOhneBegruendung"

    assert parsed.analysis.ok_count == 3
    assert parsed.analysis.header_ok
    assert parsed.column(column) is not None
    values = list(parsed.values(column))
    assert values == ["", "", ""]
    # Empty means "no value provided" (§8.6) — not a missing column.
    assert all(len(row) == 67 for row in parsed.rows)


# --- h09 -------------------------------------------------------------------


def test_h09_lossy_french_contributes_zero_to_the_canary(hz):
    """French with `oe` and typographic quotes already deleted upstream."""
    parsed = hz.parse("h09_fr_lossy", "text.csv")
    narratives = list(parsed.values(TEXT_NARRATIVE_COLUMN))

    assert len(narratives) == 3
    assert count_canary_chars(narratives) == 0

    finding = canary_finding(0, ["de", "fr", "it"])
    assert finding is not None
    assert finding.code is FindingCode.CP1252_CANARY_ZERO
    assert finding.severity is Severity.REPORTED
    # The offending datum for a corpus-level check is the count itself.
    assert finding.detail["canary_count"] == "0"
    assert "fr" in finding.detail["languages"]


def test_h09_zero_without_french_is_not_evidence(hz):
    """Zero in a German-only corpus proves nothing and must not be reported."""
    assert canary_finding(0, ["de"]) is None


# --- h10 -------------------------------------------------------------------


def test_h10_count_mismatch_is_reported_with_the_key_and_does_not_block(hz):
    """`AnzObjFeld` says 3, two `objekt` rows exist."""
    analysis = validate_delivery(hz.parse_all("h10_count_mismatch"))
    key = hz.uid("aa", 1)

    finding = hz.only(analysis.findings, FindingCode.COUNT_MISMATCH_OBJ)
    assert finding.severity is Severity.REPORTED
    assert finding.key == key
    assert key in hz.detail_values(finding)
    assert finding.detail["declared"] == "3"
    assert finding.detail["actual"] == "2"

    assert blocking_findings(analysis) == ()
    # The person count is right, so exactly one mismatch fires.
    assert hz.of_code(analysis.findings, FindingCode.COUNT_MISMATCH_PERS) == []


# --- h11 -------------------------------------------------------------------


def test_h11_text_row_with_no_unfall_row_is_reported_with_its_key(hz):
    """A narrative that joins to nothing. Reported, non-blocking."""
    analysis = validate_delivery(hz.parse_all("h11_unmatched_text_key"))
    missing = hz.uid("ff", 998)

    finding = hz.only(analysis.findings, FindingCode.TEXT_KEY_UNMATCHED)
    assert finding.severity is Severity.REPORTED
    assert finding.key == missing
    assert missing in hz.detail_values(finding)

    assert blocking_findings(analysis) == ()
    # The one `unfall` row does have a narrative, so its converse never fires.
    assert hz.of_code(analysis.findings, FindingCode.UNFALL_WITHOUT_TEXT) == []


# --- h12 -------------------------------------------------------------------


def test_h12_unknown_header_is_unknown_and_blocking_when_selected(hz):
    """No match -> `unknown`, blocking the moment the analyst selects it."""
    parsed = hz.parse("h12_unknown_header", "unknown.csv", selected=True)

    assert parsed.analysis.kind is FileKind.UNKNOWN
    assert parsed.analysis.header_ok is False

    finding = hz.only(parsed.analysis.findings, FindingCode.UNKNOWN_HEADER)
    assert finding.severity is Severity.BLOCKING
    # The offending datum for an unrecognised file is its header.
    assert finding.detail["header"] == "REPORT_ID;SUBMITTED_ON;OFFICER_REMARKS"
    assert finding.detail["columns"] == "3"


def test_h12_unknown_header_is_only_reported_when_deselected(hz):
    """An unknown file nobody selected is a note, not a blocker (§6.2.2)."""
    parsed = hz.parse("h12_unknown_header", "unknown.csv", selected=False)
    finding = hz.only(parsed.analysis.findings, FindingCode.UNKNOWN_HEADER)
    assert finding.severity is Severity.REPORTED
    assert parsed.analysis.has_blocking is False


def test_h12_rows_are_not_key_anchored_when_the_kind_is_unknown(hz):
    """With no known key column there is nothing to anchor on, so the rows are
    read straight rather than each being called a continuation of the last."""
    parsed = hz.parse("h12_unknown_header", "unknown.csv")
    assert parsed.analysis.ok_count == 2
    assert parsed.analysis.rejected_count == 0
    assert hz.of_code(parsed.analysis.findings, FindingCode.ROW_REJECTED_PARSE_ERROR) == []


# --- the rule underneath all twelve ---------------------------------------


@pytest.mark.parametrize(
    ("hazard", "filename"),
    [
        ("h03_stray_delimiter", "unfall.txt"),
        ("h04_embedded_newline", "text.csv"),
        ("h05_unquoted_newline", "text.csv"),
        ("h12_unknown_header", "unknown.csv"),
    ],
)
def test_no_row_is_ever_silently_repaired_or_dropped(hz, hazard, filename):
    """§12.6, as an assertion: physical outcomes and reported findings agree.

    Every recovered row and every rejected row has a finding of its own, so the
    counts on `FileAnalysis` can never claim something the report does not.
    """
    parsed = hz.parse(hazard, filename)
    findings = parsed.analysis.findings

    recovered = hz.of_code(findings, FindingCode.ROW_RECOVERED)
    rejected = hz.of_code(findings, FindingCode.ROW_REJECTED_FIELD_COUNT) + hz.of_code(
        findings, FindingCode.ROW_REJECTED_PARSE_ERROR
    )

    assert len(recovered) == parsed.analysis.recovered_count
    assert len(rejected) == parsed.analysis.rejected_count
    assert parsed.analysis.row_count == (
        parsed.analysis.ok_count + parsed.analysis.recovered_count + parsed.analysis.rejected_count
    )
    assert len(parsed.rows) == parsed.analysis.ok_count + parsed.analysis.recovered_count


@pytest.mark.parametrize(
    ("hazard", "filename", "expected"),
    [
        ("h01_cp1252", "unfall.txt", FileKind.UNFALL),
        ("h04_embedded_newline", "text.csv", FileKind.TEXT),
        ("h12_unknown_header", "unknown.csv", FileKind.UNKNOWN),
    ],
)
def test_the_filename_never_decides_the_kind(hz, hazard, filename, expected):
    """SD5 / §12.5, as an assertion: the same bytes under four misleading names
    give the same `FileKind`, because only the header is ever consulted."""
    data = hz.bytes_of(hazard, filename)
    for alias in ("person.txt", "objekt.csv", "narrative-2025.dat", "unfall_BE_2025.txt"):
        renamed = analyse_file(file_id=FileId(alias), filename=alias, data=data)
        assert renamed.analysis.kind is expected, alias


def test_every_hazard_directory_exists(hz):
    """The twelve of sw-design.md §11.4, all committed, none quietly missing."""
    found = sorted(p.name for p in hz.dir.iterdir() if p.is_dir())
    assert [name[:3] for name in found] == [f"h{n:02d}" for n in range(1, 13)]


def test_no_hazard_row_outcome_is_unaccounted(hz):
    """Every outcome the enum defines is exercised somewhere in the twelve."""
    seen = set()
    for directory in sorted(p for p in hz.dir.iterdir() if p.is_dir()):
        for path in sorted(directory.iterdir()):
            parsed = hz.parse(directory.name, path.name)
            if parsed.analysis.ok_count:
                seen.add(RowOutcome.OK)
            if parsed.analysis.recovered_count:
                seen.add(RowOutcome.RECOVERED)
            if parsed.analysis.rejected_count:
                seen.add(RowOutcome.REJECTED)
    assert seen == set(RowOutcome)
