"""Key-anchored recovery: repaired where it is unambiguous, rejected where it
is not (mvp-spec.md §4.2.3)."""

import pytest

from ra2.domain.delivery import Dialect, FileKind, RowOutcome
from ra2.domain.findings import FindingCode, Severity
from ra2.domain.parsing.reader import RawRow
from ra2.domain.parsing.recovery import KEY_ANCHOR, is_key_anchor, recover_rows

SEMI = Dialect(delimiter=";")
PIPE = Dialect(delimiter="|")
KEY_A = "aa" + "0" * 29 + "1"
KEY_B = "aa" + "0" * 29 + "2"


def run(raw, *, kind, dialect, expected):
    return list(
        recover_rows(raw, kind=kind, dialect=dialect, expected_field_count=expected)
    )


def row(line_no, *fields, span=1, error=None):
    return RawRow(line_no=line_no, fields=tuple(fields), error=error, line_span=span)


# --- the anchor itself -----------------------------------------------------


def test_the_anchor_is_exactly_32_hex_characters():
    assert is_key_anchor((KEY_A, "x"))
    assert not is_key_anchor(("aa" + "0" * 28 + "1", "x"))  # 31
    assert not is_key_anchor(("aa" + "0" * 30 + "1", "x"))  # 33
    assert not is_key_anchor(("gg" + "0" * 29 + "1", "x"))  # not hex
    assert not is_key_anchor(())


def test_the_anchor_is_case_insensitive_because_hex_is():
    assert is_key_anchor(("AA" + "0" * 29 + "1",))
    assert KEY_ANCHOR.match("F" * 32)


def test_a_quoted_key_still_anchors():
    """Applying the rule to the parsed first field rather than the raw line is
    the same rule and a slightly stronger one: `"<32 hex>"|…` is a legitimate
    row a literal line-regex would miss."""
    assert is_key_anchor((KEY_A,))


# --- the two-column text file: repaired ------------------------------------


def test_a_continuation_line_is_glued_onto_the_previous_narrative():
    result = run(
        [row(2, KEY_A, "first half"), row(3, "second half")],
        kind=FileKind.TEXT,
        dialect=SEMI,
        expected=2,
    )
    assert len(result) == 1
    assert result[0].fields == (KEY_A, "first half\nsecond half")
    assert result[0].outcome is RowOutcome.RECOVERED
    assert result[0].key == KEY_A


def test_a_repaired_row_always_carries_a_finding_with_its_key():
    result = run(
        [row(2, KEY_A, "a"), row(3, "b")], kind=FileKind.TEXT, dialect=SEMI, expected=2
    )
    (finding,) = result[0].findings
    assert finding.code is FindingCode.ROW_RECOVERED
    assert finding.severity is Severity.REPORTED
    assert finding.key == KEY_A
    assert finding.detail["key"] == KEY_A
    assert finding.detail["method"] == "key_anchor"


def test_a_delimiter_inside_an_unquoted_narrative_is_rejoined_and_reported():
    """A two-column file's second column is "everything after the first
    delimiter", so this is determined rather than guessed — but it still
    changed the row, so it is reported (§12.6)."""
    result = run(
        [row(2, KEY_A, "vorne", "hinten")], kind=FileKind.TEXT, dialect=SEMI, expected=2
    )
    assert result[0].fields == (KEY_A, "vorne;hinten")
    assert result[0].outcome is RowOutcome.RECOVERED
    assert result[0].findings[0].detail["method"] == "delimiter_in_narrative"


def test_a_clean_text_row_is_ok_and_reports_nothing():
    result = run([row(2, KEY_A, "clean")], kind=FileKind.TEXT, dialect=SEMI, expected=2)
    assert result[0].outcome is RowOutcome.OK
    assert result[0].findings == ()


def test_a_quoted_multi_line_record_is_recovered_by_the_reader_not_the_anchor():
    result = run(
        [row(2, KEY_A, "one\ntwo", span=2)], kind=FileKind.TEXT, dialect=SEMI, expected=2
    )
    assert result[0].outcome is RowOutcome.RECOVERED
    assert result[0].findings[0].detail["method"] == "quoted"


# --- the wide tables: detected, never repaired -----------------------------


def test_a_wide_row_split_across_lines_is_rejected_not_repaired():
    """A stray `|` could have landed in any of 67 fields. Any repair would be a
    guess written into a corpus that is immutable afterwards."""
    result = run(
        [row(2, KEY_A, "a", "b"), row(3, "c", "d")],
        kind=FileKind.UNFALL,
        dialect=PIPE,
        expected=5,
    )
    assert len(result) == 1
    assert result[0].outcome is RowOutcome.REJECTED
    assert result[0].key == KEY_A
    (finding,) = result[0].findings
    assert finding.code is FindingCode.ROW_REJECTED_FIELD_COUNT
    assert finding.detail["key"] == KEY_A
    assert finding.detail["reason"] == "continuation_line"
    assert finding.detail["continuation_lines"] == "3"
    # The fields were left exactly as read — nothing was glued on.
    assert result[0].fields == (KEY_A, "a", "b")


def test_a_wide_row_is_rejected_even_when_the_field_count_would_come_out_right():
    """Detected, not repaired: a coincidence must not become a silent repair."""
    result = run(
        [row(2, KEY_A, "a", "b"), row(3, "c")],
        kind=FileKind.UNFALL,
        dialect=PIPE,
        expected=3,
    )
    assert result[0].outcome is RowOutcome.REJECTED


def test_too_many_fields_is_rejected_with_the_counts_and_the_key():
    result = run(
        [row(2, KEY_A, "a", "b", "c")], kind=FileKind.UNFALL, dialect=PIPE, expected=3
    )
    (finding,) = result[0].findings
    assert finding.code is FindingCode.ROW_REJECTED_FIELD_COUNT
    assert finding.detail["expected_fields"] == "3"
    assert finding.detail["actual_fields"] == "4"
    assert finding.key == KEY_A


def test_a_clean_wide_row_is_ok():
    result = run([row(2, KEY_A, "a", "b")], kind=FileKind.UNFALL, dialect=PIPE, expected=3)
    assert result[0].outcome is RowOutcome.OK
    assert result[0].findings == ()


# --- rows the reader could not parse at all --------------------------------


def test_a_reader_error_becomes_a_rejected_row_with_a_finding():
    result = run(
        [row(2, error="unexpected end of data")],
        kind=FileKind.TEXT,
        dialect=SEMI,
        expected=2,
    )
    assert result[0].outcome is RowOutcome.REJECTED
    (finding,) = result[0].findings
    assert finding.code is FindingCode.ROW_REJECTED_PARSE_ERROR
    assert finding.detail["error"] == "unexpected end of data"


def test_an_error_flushes_the_record_being_assembled_rather_than_losing_it():
    result = run(
        [row(2, KEY_A, "a"), row(3, error="boom"), row(4, KEY_B, "b")],
        kind=FileKind.TEXT,
        dialect=SEMI,
        expected=2,
    )
    assert [r.key for r in result] == [KEY_A, None, KEY_B]


def test_a_continuation_with_nothing_to_continue_is_reported_not_dropped():
    result = run([row(2, "orphan text")], kind=FileKind.TEXT, dialect=SEMI, expected=2)
    assert result[0].outcome is RowOutcome.REJECTED
    assert result[0].findings[0].code is FindingCode.ROW_REJECTED_PARSE_ERROR


# --- the invariant ---------------------------------------------------------


@pytest.mark.parametrize("kind", [FileKind.TEXT, FileKind.UNFALL, FileKind.OBJEKT])
def test_every_non_ok_row_carries_at_least_one_finding(kind):
    """§12.6 as a property of the function, not of one fixture."""
    raw = [
        row(2, KEY_A, "a"),
        row(3, "continuation"),
        row(4, KEY_B, "a", "b", "c"),
        row(5, error="boom"),
    ]
    dialect = SEMI if kind is FileKind.TEXT else PIPE
    for recovered in run(raw, kind=kind, dialect=dialect, expected=2):
        if recovered.outcome is not RowOutcome.OK:
            assert recovered.findings, recovered


def test_a_file_id_is_stamped_onto_every_finding_when_given():
    result = list(
        recover_rows(
            [row(2, KEY_A, "a", "b", "c")],
            kind=FileKind.UNFALL,
            dialect=PIPE,
            expected_field_count=2,
            file_id="file-1",  # type: ignore[arg-type]
        )
    )
    assert result[0].findings[0].file_id == "file-1"
